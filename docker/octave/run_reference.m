% run_reference.m -- Octave reference generator for the FHRPY parity harness.
%
% Runs the ORIGINAL FHRMA MATLAB sources (in /opt/harness/matlab_ref) under
% Octave on a handful of .fhr recordings and dumps the reference outputs that
% tests/test_matlab_parity.py compares against the NumPy ports.
%
% For each recording <name> it writes /work/out/ref_<name>.mat (MATLAB v7,
% readable by scipy.io.loadmat) containing:
%   FHR1, FHR2, MHR, TOCO   - raw decoded signals from fhropen   (read_fhr parity)
%   FHRi, FHRpre, d, f      - preprocess() outputs               (preprocess parity)
%   baseline                - aamwmfb() baseline @4Hz            (WMFB parity)
%   acc, dec, falseAcc, ... - accel/decel/false segment lists [start;end] in s
%   bl_FHR1                 - butterfilt(FHRi,240,0,1,1) the 1cpm low-pass copy
%                             used by the A/D detector (intermediate parity)
%   multisig_compiled       - 1 if multisigfilter.oct was used, 0 if filtfilt fb
%
% Driven by run.sh; the list of files is passed via the FHR_FILES env var
% (space-separated absolute paths inside the container), defaulting to the
% repo example recording.

more off;
pkg load signal;

HARNESS = '/opt/harness';
REFDIR  = fullfile(HARNESS, 'matlab_ref');
OUTDIR  = '/work/out';
if ~exist(OUTDIR, 'dir'); mkdir(OUTDIR); end
addpath(REFDIR);

% ---------------------------------------------------------------------------
% Compile the portable multisigfilter so butterfilt.m uses the ORIGINAL C
% filter path (not its filtfilt fallback). If this fails we still proceed --
% butterfilt.m catches the missing-MEX error and falls back to filtfilt.
% ---------------------------------------------------------------------------
% matlab_ref is bind-mounted read-only, so we compile into a writable build dir
% and put it FIRST on the path so multisigfilter() resolves there.
%
% multisigfilter_oct.c is a classic MATLAB-style MEX (mexFunction entry point),
% so it must be built with Octave's `mex` (i.e. mkoctfile --mex), producing a
% .mex file -- a plain `mkoctfile foo.c -o foo.oct` does NOT recognise the
% mexFunction entry point and yields an unloadable .oct.
BUILDDIR = '/work/out/build';
if ~exist(BUILDDIR, 'dir'); mkdir(BUILDDIR); end
addpath(BUILDDIR);

multisig_compiled = 0;
oldpwd = pwd();
cd(BUILDDIR);
try
    if exist(fullfile(BUILDDIR, 'multisigfilter.mex'), 'file') ~= 3
        mex(fullfile(REFDIR, 'multisigfilter_oct.c'), '-output', 'multisigfilter');
    end
    rehash();                          % make the freshly-built .mex visible
    if isempty(which('multisigfilter'))
        error('multisigfilter.mex not loadable after build');
    end
    % Smoke-test it against filtfilt on a known order-1 filter.
    [b, a] = butter(1, 0.2, 'low');
    x = sin(linspace(0, 20, 500));
    nfilt = max(length(b), length(a));
    rows = [1:nfilt-1  2:nfilt-1  1:nfilt-2];
    cols = [ones(1,nfilt-1) 2:nfilt-1  2:nfilt-1];
    tdata = [1+a(2) a(3:nfilt) ones(1,nfilt-2) -ones(1,nfilt-2)];
    sp = sparse(rows, cols, tdata);
    zi = sp \ (b(2:nfilt).' - a(2:nfilt).'*b(1));
    % Use feval so the parser resolves the freshly-built .mex at run time
    % (a direct call can be bound to "undefined" when run() pre-parses).
    y_c  = feval('multisigfilter', b, a, x', zi)';
    y_ff = filtfilt(b, a, x);
    fprintf('multisigfilter.mex compiled; max|c-filtfilt| (order1) = %.3e\n', ...
            max(abs(y_c - y_ff)));
    multisig_compiled = 1;
catch err
    fprintf(2, 'multisigfilter compile/test FAILED: %s\n', err.message);
    fprintf(2, 'butterfilt.m will fall back to filtfilt.\n');
end
cd(oldpwd);

% ---------------------------------------------------------------------------
% File list
% ---------------------------------------------------------------------------
files_env = getenv('FHR_FILES');
if isempty(files_env)
    files = {'/work/repo/examples/example_recording.fhr'};
else
    files = strsplit(strtrim(files_env));
end

for k = 1:numel(files)
    fpath = files{k};
    if isempty(fpath); continue; end
    [~, name, ext] = fileparts(fpath);
    fprintf('\n=== %s%s ===\n', name, ext);

    % --- fhropen: raw decoded signals (read_fhr parity) ---
    [FHR1raw, FHR2raw, MHR, TOCO, timestamp, infos] = fhropen(fpath); %#ok<ASGLU>

    % --- preprocess (preprocess parity) ---
    % preprocess.m returns [FHRi, FHR(with NaN), TOCO, d, f].
    [FHRi, FHRpre, TOCOpre, d, f] = preprocess(FHR1raw, FHR2raw, TOCO); %#ok<ASGLU>

    % --- aamwmfb: baseline + accel/decel (WMFB parity) ---
    t0 = tic;
    [baseline, accelerations, decelerations, falseAcc, falseDec] = aamwmfb(FHRi);
    fprintf('aamwmfb done in %.1fs (N=%d samples)\n', toc(t0), numel(FHRi));

    % --- the 1 cpm low-pass copy used internally by the A/D detector ---
    bl_FHR1 = butterfilt(FHRi, 240, 0, 1, 1);

    % aamwmfb returns acc/dec as 2xK (or 3xK) [start;end;...] in SECONDS.
    acc      = accelerations;
    dec      = decelerations;
    falseAcc = falseAcc;
    falseDec = falseDec;

    % --- contractions: the accelerations of aamwmfb(TOCO*2) (amnio BLsam(TOCO*2)) ---
    % TOCO is the raw fhropen output (byte/2), exactly what fhrpy.detect_contractions
    % feeds as wmfb(record.toco * 2).
    [~, contractions, ~] = aamwmfb(double(TOCO) * 2);

    % --- standard CTG features over the valid window [d:f] (compute_features parity) ---
    w = max(1, d):min(numel(FHRi), f);
    feat = struct();
    feat.fhr_mean = mean(FHRi(w));
    feat.baseline_mean = mean(baseline(w));
    feat.fhr_time_below_110_percent = sum(FHRi(w) < 110) / numel(w) * 100;
    feat.fhr_time_above_160_percent = sum(FHRi(w) > 160) / numel(w) * 100;
    feat.baseline_time_below_110_percent = sum(baseline(w) < 110) / numel(w) * 100;
    feat.stv_msd = mean(abs(diff(FHRi(w))));
    feat.acc_count = size(acc, 2);
    feat.dec_count = size(dec, 2);
    feat.contraction_count = size(contractions, 2);
    if size(dec, 2) > 0
        dd = extractAccDecDataAmnio(dec, FHRi, baseline, 'dec');
        feat.dec_amplitude_mean = mean(dd.amplitude);
        feat.dec_surface_total = sum(dd.surface);
        feat.dec_duration_mean = mean(dd.duration);
    else
        feat.dec_amplitude_mean = NaN; feat.dec_surface_total = 0; feat.dec_duration_mean = NaN;
    end

    outfile = fullfile(OUTDIR, sprintf('ref_%s.mat', name));
    save('-v7', outfile, ...
        'FHR1raw', 'FHR2raw', 'MHR', 'TOCO', 'timestamp', ...
        'FHRi', 'FHRpre', 'TOCOpre', 'd', 'f', ...
        'baseline', 'bl_FHR1', ...
        'acc', 'dec', 'falseAcc', 'falseDec', ...
        'contractions', 'feat', ...
        'multisig_compiled');
    fprintf('wrote %s\n', outfile);
end

fprintf('\nAll references written to %s\n', OUTDIR);
