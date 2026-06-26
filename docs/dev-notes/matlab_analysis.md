# FHRMA Toolbox — Port Specification (MATLAB → Python/NumPy)

Source root: `/home/sam/Desktop/fhr-demo/matlab/src/FHRMA/`
Author: Samuel Boudet et al. (GPL v3, see `LICENSE`). Papers [1]-[6] in `README.md`.
All signals are sampled at **4 Hz** unless noted. Note: in several inner DSP routines the code uses **240** as the sampling rate; that is `4 Hz * 60` because durations are sometimes expressed per-minute. **The actual sample rate is 4 Hz**, but `butterfilt(...,240,...)` is called with `srate=240`, which means the cutoff frequencies passed are in "cycles per minute" (e.g. a `f2=1` low-pass at `srate=240` = cutoff at 1/240 of Nyquist=120 → 0.5 cycles/min ≈ 0.0083 Hz). Keep srate=240 verbatim when porting to reproduce results exactly.

MEX/Windows binaries (`*.mexw32/64`) are not portable; `multisigfilter.c` must be reimplemented (section 7). Everything else is plain `.m`.

---

## 1. FILE FORMAT (`fhropen.m`, `fhrsave.m`)

Four file types, dispatched by extension. All multi-byte integers are **little-endian** (MATLAB `fread` default on x86). Records are interleaved per-sample (AoS layout), NOT channel-contiguous. The trick used in `fhropen`: read the same bytes twice with two different type/shape interpretations.

### 1.1 `.fhr` / `.rcf`  (no MHR) — 10 bytes per sample
- Header: 1 × `uint32` = unix `timestamp` (4 bytes).
- Then N records, each 10 bytes:
  - bytes 0-1: `uint16` FHR1raw  → `FHR1 = FHR1raw/4`  (bpm)
  - bytes 2-3: `uint16` FHR2raw  → `FHR2 = FHR2raw/4`
  - bytes 4-5: `uint16` (unused here; in fhrsave this slot is part of the uint16 triple only when MHR present — for `.fhr` only 2 uint16 are written, so bytes 4-9 are the 6 uint8 below)
  - Actually the read is done in two passes (see code): pass A reads `[3 x n] uint16` from offset 4 → rows 1,2 = FHR1,FHR2 (row 3 discarded). Pass B `fseek` to offset 4, reads `[6 x n] uint8`: row 5 = `TOCO*2` → `TOCO = row5/2`. So the 10-byte record = `[FHR1:u16][FHR2:u16][TOCO_in_3rd_u16_low_byte... ]`. **Concretely the 10 bytes are: FHR1(2) FHR2(2) ?(2) TOCO_byte(1) Q_byte(1) ...** — to be safe, replicate the dual-read exactly:
    - `u16 = frombuffer(data[4:], '<u2').reshape(-1,3)`; FHR1=u16[:,0]/4, FHR2=u16[:,1]/4
    - `u8  = frombuffer(data[4:], '<u1').reshape(-1,6)`; TOCO = u8[:,4]/2
  - MHR = zeros. infos = empty.

### 1.2 `.fhrm` / `.rcfm`  (with MHR + sensor-quality flags) — 12 bytes per sample
- Header: `uint32` timestamp (4 bytes).
- Pass A from offset 4: `[4 x n] uint16` → FHR1=row1/4, FHR2=row2/4, MHR=row3/4. (row4 holds the TOCO+Q byte pair.)
- Pass B `fseek(4)`: `[8 x n] uint8` → TOCO = row7/2, `Q = row8` (a 7-bit flag byte).
- 12-byte record layout: `FHR1(u16) FHR2(u16) MHR(u16) TOCO(u8) Q(u8)`.
- `Q` bit decoding (`dec2bin(Q,7)`, MSB-first string `C`, indexing C(:,7) = LSB):
  - `infos.Q1     = bit0` (FHR1 good quality)
  - `infos.isECG1 = bit1` (FHR1 from scalp ECG, else Doppler)
  - `infos.Q2     = bit2`
  - `infos.isECG2 = bit3`
  - `infos.Qm     = bit4` (MHR good quality)
  - `infos.isTOCOMHR = bit5` (MHR from toco belt, else finger oximeter)
  - `infos.isIUP   = bit6` (TOCO from internal sensor)
  - In Python: `Q1 = Q & 1`, `isECG1=(Q>>1)&1`, `Q2=(Q>>2)&1`, `isECG2=(Q>>3)&1`, `Qm=(Q>>4)&1`, `isTOCOMHR=(Q>>5)&1`, `isIUP=(Q>>6)&1`.

### 1.3 `.dat` (Physionet CTU-UHB) — 4 bytes per sample, no header
- `[2 x n] uint16 / 100`: FHR1 = row1/100, TOCO = row2/100. FHR2=MHR=zeros, timestamp=0.

### 1.4 Scaling summary
- FHR/MHR stored as `uint16 = bpm*4` → divide by 4. Resolution 0.25 bpm.
- TOCO stored as `uint8 = toco*2` → divide by 2.
- Missing signal is coded as **0** bpm.

### 1.5 `fhrsave.m`
Writes timestamp(u32), then per-sample interleaved: `[FHR1;FHR2;MHR]*4` as u16 (or just FHR1,FHR2 if MHR empty), then `[TOCO*2; Q]` as u8, optionally `[FHRi;baselineFHR]*4` u16 (analysis variant `.fhra`). `Q = Q1 + 2*isECG1 + 4*Q2 + 8*isECG2 + 16*Qm + 32*isTOCOMHR + 64*isIUP`.

---

## 2. WMFB BASELINE ALGORITHM (`aamwmfb.m`) — KEY PORT

Paper [5]. Entry: `[baseline, accelerations, decelerations, falseAcc, falseDec] = aamwmfb(FHRi)`.
Input `FHRi`: FHR at 4 Hz, **interpolated, no signal loss** (from `preprocess`). Output `baseline` at 4 Hz; accel/decel are `3 x n` columns `[start; end; max]` (after division `/4` → seconds; note `adjustduration(...)/4` converts sample index → seconds-at-4Hz... actually `/4` converts samples to seconds since fs=4).

### 2.1 Multi-bandwidth low-pass copies (zero-phase Butterworth, order 1)
All via `butterfilt(FHRi, 240, 0, fc, 1, 1)` (low-pass, order 1, zero-phase):
```
FHR1  = LP @ fc=1   (srate=240)
FHR2  = LP @ fc=2
FHR4  = LP @ fc=4
FHR8  = LP @ fc=8
FHR16 = LP @ fc=16
```
(cutoffs are cycles/min: real Hz = fc/60.)

### 2.2 Signal-trust probability `P` (logistic on derivative-envelope features)
```
fcut = [0 1 3 7]
for j=1..3:
    fdat{j,1} = butterfilt(FHRi,240,fcut(j),fcut(j+1),1)       % band-pass order 1 zero-phase
    fdat{j,2} = [0, diff(fdat{j,1})]*240                       % derivative (×srate)
t = [ abs(fdat{1,2}) ;
      enveloppe(fdat{1,2},240,0,2*fcut(2)) ;
      enveloppe(fdat{2,2},240,0,2*fcut(3)) ;
      enveloppe(fdat{3,2},240,0,2*fcut(4)) ]'      % N×4 feature matrix
Q = [-2.4744; 0.0266; 0.0413; 0.0105; 0.0036]
lin = Q(1) + t*Q(2:5)
P = 1 - exp(lin)./(1+exp(lin))   = 1 - sigmoid(lin) = sigmoid(-lin)
```
`enveloppe(x,srate,f0,f1)` = analytic-signal-like band envelope via FFT (section 3.7). `P` is a per-sample trust weight in [0,1] (P high ⇒ trustworthy/quiet signal).

### 2.3 Iterative weighted-median-filter bank (the core)
`distancecoef = [linspace(0,1,200), 1, linspace(1,0,200)]` → length 401 triangular window (the median window weight by position). `decim=24` (decimation factor used inside `medgliss`).

Six successive passes; each refines the baseline using a progressively smoother FHR copy and a triangular weight raised to higher powers, plus an attraction term toward the previous baseline:
```
[bl1,mp1] = medgliss(FHR2 , distancecoef    , P'      , 24)
P2 = P' .* sigmoid( 3.21 - 0.19*abs(FHR1 - bl1) )
[bl2]     = medgliss(FHR2 , distancecoef.^2 , P2 , 24, bl1, mp1, 0.1)
P3 = P' .* sigmoid( 2.5  - 0.19*abs(FHR4 - bl2) )
[bl3]     = medgliss(FHR4 , distancecoef.^4 , P3 , 24, bl2, mp1, 0.1)
P4 = P' .* sigmoid( 2.0  - 0.19*abs(FHR8 - bl3) )
[bl4]     = medgliss(FHR8 , distancecoef.^8 , P4 , 24, bl3, mp1, 0.1)
P5 = P' .* sigmoid( 1.5  - 0.19*abs(FHR16- bl4) )
[bl5]     = medgliss(FHR16, distancecoef.^16, P5 , 24, bl4, mp1, 0.1)
P6 = P' .* sigmoid( 1.0  - 0.19*abs(FHR16- bl5) )
[bl6]     = medgliss(FHR16, distancecoef.^16, P6 , 24, bl5, mp1, 0.1)
baseline = bl6
```
where `sigmoid(x)=exp(x)/(1+exp(x))`. Intuition: each pass pulls the running weighted median toward the previous baseline (weight `c=0.1`) so distant accelerations/decels are progressively rejected; smoother FHR copies (FHR4/8/16) are used as passes progress.

### 2.4 `medgliss(X, win, coef, decim, X2?, p2?, c?)` — weighted sliding median
This is the heart. Returns `Y` (baseline, length of X) and `mp` (mean weight).
```
Xd = butterfilt(X,240,0,240/2.2/decim,8,1)      % anti-alias LP order 8 zero-phase
Xd = Xd(1:decim:end)                            % decimate by `decim` (=24 → effective 10 Hz? fs/24)
if X2 given: X2 = X2(1:decim:end)
coefd = decimate(double(coef),decim)            % MATLAB signal.decimate (FIR/IIR + filter); coefd=max(coefd,0)
midwin = (length(win)-1)/2                       % =200 for the 401-length win
```
Tolerance band (limits the median to values within the local 10-min min/max envelope):
```
mintolerated = zeros; maxtolerated = 255*ones
for i = 1 : (240/2/decim) : length(Xd)-10*240/decim     % step=5 (=240/2/24), window 10*240/24=100 samples
    twin = i : i+10*240/decim
    mi=min(Xd(twin)); ma=max(Xd(twin))
    mintolerated(twin where mintolerated<=mi)=mi
    maxtolerated(twin where maxtolerated<=ma)=ma
```
Main weighted-median loop over decimated samples i:
```
for i=1..length(Xd):
   determine asymmetric half-windows mwm,mwp near borders (see code lines 152-161):
       if i-1<midwin:  mwm=i-1; mwp=min(max(mwm, floor((midwin-mwm)/2)), len-i)
       elseif len-i<midwin: mwp=len-i; mwm=min(max(mwp, floor((midwin-mwp)/2)), i-1)
       else: mwm=mwp=midwin
   points = i-mwm : i+mwp
   Xpoints = Xd(points)
   coefwin = coefd(points) .* win(midwin-mwm+1 : midwin+mwp+1) .* (Xpoints in [mintol(i),maxtol(i)])
   s = sum(coefwin);  scoef = sum(win(midwin-mwm+1:midwin+mwp+1))
   if X2 given (attraction to previous baseline):
       Xpoints = [Xpoints, X2(i)]
       coefwin = [coefwin, max(0, c*p2(i)*scoef - s)]      % extra weight pulling toward X2(i)
       s = sum(coefwin)
   [p,order]=sort(Xpoints)
   Yd(i) = p( first index where cumsum(coefwin(order)) >= s/2 )   % weighted median
   mp(i) = s/scoef
Y  = interp(Yd, decim); Y = Y(1:length(X))      % MATLAB interp() = upsample+LP interpolation
mp = interp(mp, decim); mp = mp(1:length(X))
```
Port notes:
- `decimate(coef,24)` and `interp(Yd,24)` are MATLAB `signal` functions (decimate = 8th-order Chebyshev LP + downsample by default; interp = zero-stuff + LP FIR). For an exact port use `scipy.signal.decimate(coef, 24)` and an `interp`-equivalent (FIR interpolation, gain `decim`). Acceptable approximations: `scipy.signal.resample_poly`. The baseline is robust to small interpolation differences but for bit-exactness mirror MATLAB's `interp`/`decimate` filters.
- The weighted median: sort values, take the first whose cumulative weight ≥ half of total weight.

### 2.5 Acceleration / Deceleration extraction inside aamwmfb
```
accelerations = accidentcandidat(FHR1, baseline, 5)              % regions where FHR1-baseline>5 bpm
accelerations = adjustduration(accelerations, FHRi-baseline)/4   % refine start/end to zero-crossings, split, →seconds
[accelerations,falseAcc] = validaccident(accelerations, FHRi-baseline, 15, 15)  % keep dur≥15s & amp≥15bpm
decelerations = accidentcandidat(baseline, FHR1, 5)
decelerations = adjustduration(decelerations, baseline-FHRi)/4
[decelerations,falseDec] = validaccident(decelerations, baseline-FHRi, 15, 15)
```
`accidentcandidat(s1,s2,seuil)`: binary `s1-s2>seuil`, `startendlist` of runs → rows `[start;end]`, then row3 = argmax of `s1-s2` within each run (sample of peak). See section 4.
`adjustduration(startendlist,s)` (lines 89-112): for each candidate, shrink end back to last sample before `s<0` after the peak; if the trimmed-off tail is ≥15*4 samples and contains a positive max, spawn a new candidate (handles back-to-back accidents). Same on the start side. Operates in 4-Hz samples; final `/4` → seconds.

---

## 3. PREPROCESS PIPELINE & HELPERS

### 3.1 `preprocess(FHR1,FHR2,TOCO,unreliableSignal?)` → `[FHRi,FHR,TOCO,d,f]`
```
FHR = max(FHR1,FHR2)                              % element-wise merge of the two sensors
if unreliableSignal given (n×2, in seconds):
    for each row: FHR(round(r1*240+1):round(r2*240)) = 0     % NOTE *240 (=4*60): rows are in MINUTES
FHR = removesmallpart(FHR)
d = first index FHR>0
[FHRi,d,f] = interpolFHR(FHR)                     % linear interp over gaps; FHRi has no zeros
FHR(FHR==0) = NaN                                 % FHR = raw with NaN gaps
```
Returns `FHRi` (gap-free, for analysis), `FHR` (raw w/ NaN), TOCO unchanged. `d`,`f` = first/last valid sample. (Note: `unreliableSignal` and other annotation time bases use 240 = 4 Hz×60 → annotation columns are in **minutes**.)

### 3.2 `removesmallpart(FHR)`
```
FHR(FHR>220 | FHR<50) = 0                          % clip physiologic range
% pass 1: remove valid runs shorter than 5*4=20 samples (5 s)
n = starts of zero→positive transitions
for each: if next-zero gap f < 5*4: zero out FHR(n:n+f)
% pass 2: remove runs shorter than 30*4=120 samples (30 s) that are large jumps both sides
for each short(<30*4) run: compare to lastvalid/nextvalid; if both ends jump <-25 OR both >25 bpm, zero it out
```

### 3.3 `interpolFHR(FHR)` → `[FHR,d,f]`
Replaces zeros/NaN by linear interpolation; extends first valid value backward to start and last valid value forward to end. `d`=first valid, `f`=last valid.
```
n=first FHR>0 & ~NaN; FHR(1:n)=FHR(n); d=n
loop: find next gap start n, next valid nf; FHR(n-1:nf)=linspace(FHR(n-1),FHR(nf),nf-n+2); n=nf
f=last valid; FHR(f:end)=FHR(f)
```

### 3.4 `butterfilt(data, srate, f1, f2, order, zeroPhase)`
Wrapper around MATLAB `butter` + filtering. `data` is channels-on-rows.
- `f1=0,f2>0` → `butter(order, 2*f2/srate, 'low')`
- `f1>0,f2=0` → high-pass at f1
- `0<f2<f1`  → band-stop `[f2 f1]`
- `0<f1<f2`  → band-pass `[f1 f2]`
- `zeroPhase=1`: builds initial conditions `zi` (solving sparse linear system, same as MATLAB `filtfilt`) then calls `multisigfilter(b,a,data',zi)'` (the MEX, section 7) — equivalent to `scipy.signal.filtfilt(b,a,data,axis=...)` with method='pad'/Gustafsson. Falls back to `filtfilt` if MEX missing.
- `zeroPhase=0`: plain causal `filter(b,a,·)` per row.
Port: `b,a = scipy.signal.butter(order, Wn, btype, fs=srate)` with `Wn` in same normalized terms (`2*f/srate` is MATLAB's normalized-by-Nyquist convention; scipy wants `fs=srate, Wn=f`). Use `scipy.signal.filtfilt(b,a,x)` for zeroPhase. The MEX implements filtfilt with `nfact=3*(order-1)` edge reflection — scipy's filtfilt default `padlen=3*max(len(a),len(b))` differs slightly; for exactness reimplement per section 7.

### 3.5 `avgwin(x,winl)` — centered moving average, window `[i-winl, i+winl]` clamped to edges. (NumPy: convolution with edge handling / cumulative-sum.)

### 3.6 `avgsubsamp(x,factor)` — non-overlapping block-mean downsample: `y(i)=mean(x((i-1)*factor+1:i*factor))`. `resamp(x,factor,l,lin?)`: linear up-sample (`lin` set) interpolating `factor` points between samples, else MATLAB `interp`; pad to length `l` with last value. `linearinterpolation(x,y,xx)` — piecewise-linear interp/extrapolation (spline-signature replacement).

### 3.7 `enveloppe(x,srate,f0,f1)` (local fn in aamwmfb) → `[y,x]`
Band envelope via FFT band-selection + Hilbert-like magnitude:
```
fftx=fft(x); siglen=length(x)/srate
firstsamp=round(f0*siglen+1); lastsamp=round(f1*siglen+1)
ffty=zeros; place fftx(firstsamp:lastsamp) into a centered (one-sided→analytic) band of ffty
   (parity branch handles even/odd band length, lines 198-203)
y = 2*abs(ifft(ffty))                              % envelope magnitude
if nargout==2: also return band-passed x (zeroing out-of-band bins symmetric)
```
Port with `numpy.fft`. Replicate the exact bin indices and the even/odd parity branch.

---

## 4. ACCEL / DECEL / CONTRACTION DETECTION & EVALUATION

### 4.1 `startendlist(binsig)` — runs of 1s → `2×k` `[start;end]` (pad binsig with 0 each side; diff to find edges).

### 4.2 `accidentcandidat(s1,s2,seuil)` (in aamwmfb) — regions `s1-s2>seuil`; appends row3 = peak sample (argmax of s1-s2 in each run).

### 4.3 `validaccident(accidents, varsig, durationthreshold, amplitudethreshold)` → `[accidents,reject]`
```
keep only accidents with (end-start) >= durationthreshold      % start/end here in SECONDS
for each: valid if max(varsig(start*4:end*4)) >= amplitudethreshold
return kept and rejected
```
WMFB uses `durationthreshold=15` s, `amplitudethreshold=15` bpm. (`varsig`=FHR-baseline for accel.)

### 4.4 `simpleaddetection(fhr,baseline)` → `[acc,dec,falseacc,falsedec]`
Trivial reference detector (3×n `[start;end;max]` in **seconds**):
```
acc = detectaccident(fhr-baseline, 15)             % true accel: dev>15 bpm
dec = detectaccident(baseline-fhr, 15)
falseacc = minusint(acc, detectaccident(fhr-baseline, 5))   % 5-bpm events not containing a true one
falsedec = minusint(dec, detectaccident(baseline-fhr, 5))
```
`detectaccident(sig,thre)`: find peaks `sig>thre`; for each, extend to surrounding zero-crossings of `sig`; keep if duration `facc-dacc > 15*4` samples (>15 s); record `[dacc;facc;macc]/4` (seconds). `minusint(a,f)`: remove from f any interval fully inside an interval of a.

**Contractions**: There is **no dedicated contraction-detection algorithm in the ported core**. TOCO is read and plotted (`fhrplot*`), and "uterine activity/contractions" are handled only via the GUI/expert annotations and the other-author methods (e.g. `aamhouze` uses TOCO). For the Python port, "contractions" = TOCO channel + (optionally) the same threshold/run logic applied to TOCO; the expert datasets do NOT store contraction labels. Treat contraction detection as out-of-scope unless re-derived from TOCO with `startendlist`-style thresholding.

### 4.5 `statscompare(FHR,LDB1,LDB2,acc1,acc2,overshoots)` → struct of discordance indices
Compares two analyses (`acc*{1}`=accel, `acc*{2}`=decel, n×2 in **minutes**). Key metrics (full list documented in header lines 11-42):
- `MADI` (Morphological Analysis Discordance Index): `mean(D./(D1.*D2+D))` with `D1,D2` = sqrt of 240-sample (1-min) moving mean of squared (baseline−FHR) +3; `D` = squared baseline difference over the central region. **Primary criterion** (median over dataset).
- `RMSD_bpm`, `Diff_Over_15_bpm_prct`, `Index_Agreement`.
- Per-accident matching (`accMatch`): match accel/decel between analyses with 5/60-min overlap tolerance; counts Match / Only_1 / Only_2 / Doubled; F-measure; start/length RMSD; overshoots excluded.
- Jezeski synthetic inconsistency `ASI_prct`, `DSI_prct`, `SI_prct=(ASI+2*DSI)/3` from cumulative FHR-baseline areas.
- `filteraccident`: drop accidents whose underlying FHR is >33% missing.

### 4.6 `evaluateaam(command, expertbase, folder)` — batch evaluator
For each file in expert DB: `fhropen` → `preprocess(...,unreliableSignal)` → run method (`eval('aamwmfb(FHR)')` returning `[baseline,accel,decel]`; accel/decel `1:2,:'/60` → minutes) OR load saved `.mat`. Zero out `notToAnalyse` + last 1 s. `statscompare` vs `expertbase(i).baseline/accelerations/decelerations/overshoots`. Median row prepended. Example: `MADI=median([fileresults.MADI])`.

---

## 5. FALSE-SIGNAL (FS) DETECTION — deep-learning, recurrent (GRU) bidirectional

Paper [6] (Biosensors 2022). Detects samples where a heart-rate channel is a "false signal" (typically Doppler picking up **maternal** HR instead of fetal, or holds/artefacts). Three models: **FSMHR** (MHR channel), **FSDop** (Doppler FHR, uses MHR as helper), **FSScalp** (scalp-ECG FHR). Framework: **TensorFlow / Keras** (training), re-implemented as plain matrix ops in MATLAB inference (`FalseSigDetectDopMHR.m`, `FalseSigDetectScalp.m`) — so a NumPy port is straightforward and needs NO TF at inference time.

### 5.1 Inference input encoding (per 4-Hz sample)
- FalseSigDetectDopMHR (`I` is `5×N`, transposed to `N×5` inside):
  ```
  I = [ (FHR>0).*(FHR-120)/60 ;   % normalized FHR (bpm→ ~[-1,1.6]); 0 where missing
        FHR>0 ;                    % FHR present mask
        (MHR>0).*(MHR-120)/60 ;    % normalized MHR
        MHR>0 ;                    % MHR present mask
        isStage2 ]                 % 0/1 second-stage-of-labor flag
  ```
- FalseSigDetectScalp (`I` is `3×N`): `[ (FHR>0).*(FHR-120)/60 ; FHR>0 ; isStage2 ]`, after `removeholds` (zero out ≥12 consecutive identical samples = sensor hold; plus short-tail cleanups, lines 46-83).
- Output `P*` = per-sample probability of being a false signal (sigmoid, [0,1]). `FHRtrue` = FHR with samples where `P≥0.5` set to missing (0).

### 5.2 Network architecture (re-coded in MATLAB; weights in `FSDop.mat`, `FSScalp.mat`)
Bidirectional stacked GRUs implemented by concatenating the signal and its time-reverse along a "batch"/page dim, running a custom forward GRU, then recombining. Custom `GRU(I,W,U,B)`:
- `W` = input kernel (`m×3n`), `U` = recurrent kernel (`n×3n`), `B` = `2×3n` bias (two bias rows: input bias + recurrent bias — Keras `reset_after=True` convention).
- Gate order in the `3n` columns: `[z (update) | r (reset) | h (candidate)]`.
- Recurrence (matches code lines 92-99):
  ```
  z = sigmoid( Wx[:,0:n] + Uh[:,0:n] + B[0,0:n] + B[1,0:n] )
  r = sigmoid( Wx[:,n:2n] + Uh[:,n:2n] + B[0,n:2n] + B[1,n:2n] )
  h = tanh( Wx[:,2n:3n] + (Uh[:,2n:3n] + B[1,2n:3n]).*r + B[0,2n:3n] )   % reset applied AFTER recurrent bias
  O_t = z.*O_{t-1} + (1-z).*h     (O_0 = (1-z).*h)
  ```
- `Dense(I,W,b)` = `sigmoid(I·W + b)`.

**FSDop forward graph** (`FalseSigDetectDopMHR.m`, lines 50-71). Weight shapes from `FSDop.mat`:
- `GRU1MHR`: W 5×36, U 12×36, B 2×36 → hidden n=12 (MHR sub-model, frozen, reused from FSMHR).
- `DensePmat`: 24×1, 1 → produces `PMat` (per-sample MHR-false probability), input = bidir GRU1MHR concat (24).
- `GRU1`: W 6×72, U 24×72, B 2×72 → n=24. Input = `[PMat, I]` (1+5=6 features) forward/back.
- `GRU2`: W 54×72, U 24×72 → n=24. Input = `[GRU1 bidir(48), PMat, I]` = 54.
- `GRU3`: W 54×72, U 24×72 → n=24. Input = `[GRU2 bidir(48), PMat, I]` = 54.
- `Dense1`: 48×1 → `PDop` from bidir GRU3 concat (48). Returns `PDop`(FHR-false prob) and `PMat`(MHR-false prob).

**FSScalp forward graph** (`FalseSigDetectScalp.m`). Shapes from `FSScalp.mat`:
- `GRU1`: W 3×72 (n=24), input = I(3 feats) bidir.
- `GRU2`: W 51×54 (n=18), input = `[GRU1 bidir(48), I(3)]`=51.
- `GRU3`: W 39×36 (n=12), input = `[GRU2 bidir(36), I(3)]`=39.
- `Dense1`: 24×1 → PFHR from GRU3 bidir(24).

Bidirectionality: stack `I` and `flipud(I)` on page-3; run GRU; for each layer recombine forward result with the time-flip of the reverse result (and carry `I`/`RevI`, and `PMat`/`RPMat` for Dop), per the `cat(3, cat(2,...), cat(2,...))` lines. Port: run the GRU twice (forward and on reversed input), flip the reverse output back, concatenate along feature axis. `pagemtimes` = batched matmul over the page dim.

NOTE on training kernels: TF models had an extra "reset" input column (index `m-1`) and recurrent-constraint sparsity masks. The exported `.mat` already **strips the reset column** (notebook cell 17: `GRU*[0]=GRU*[0][0:-1,:]`), so the inference shapes above are final — no sparsity handling needed at inference.

### 5.3 Training (Python notebooks + `4 FSScalp.py`) — framework **TensorFlow 2 / Keras**, TPU/GPU
- `1_Prepare_packaged_data.ipynb`: reads raw per-recording binaries from `dataV8.zip` (`dop###.dop` = `uint16/4` reshaped `(-1,5)`: cols FHR,MHR,labelF,labelM,isStage2; `int###.int` = `(-1,3)`: FHR,labelF,isStage2; `isval.dat`/`isvalint.dat` = train/val split bytes; `DiffMF.dat` = int16 MHR-FHR offset distribution). Labels: `isFalse = label<1`, `docare = label!=1` (value 1 = "don't care", <1 = false, >1 = true). `docare` reweighted by `sqrt(len/sum(docare))`. X normalized exactly as inference (`(hr-120)/60`, masks). Recordings bin-packed into fixed-length rows (`samp`≈57700–64800) separated by a "reset" marker column (col 5/index `m-1`), padded; pickled as `dataV8{MHR,dop,Int}{ntrain}-{nval}.pkl` with arrays `X (rows,samp,4or6)`, `Y (rows,samp,2or4)`.
- `2_Training_FSMHR.ipynb`: trains `GRU1MHR`+`DensePmat` only (MHR-false detector). 6-feature input.
- `3_Training_FSDop.ipynb`: loads frozen FSMHR weights, trains GRU1/2/3+Dense1 on top. Custom Keras `Constraint`s: `Sparsity` (block-diagonal recurrent kernel), `SparsityKernel`/`Reseter` (input kernel sparsity + a `-1e30` reset bias on the reset-input column so a reset sample forces gates/state to 0 between bin-packed recordings), `BiasConstraintCallback` (ties `W[0][-1][2L:3L] = -W[2][0][2L:3L]` so the candidate-gate input bias cancels recurrent bias → `reset_after`-consistent). Loss = `weighted_binary_crossentropy` (per-sample BCE × `docare` weight, summed). Metric `weighted_accuracy`. Optimizer Adam, LR schedule (step decays), tens of thousands of epochs, GaussianDropout 0.2/0.3/0.4.
- Heavy **on-the-fly augmentation** `siglossgenerator` (tf.function): randomly cuts the signal, drops segments of FHR/MHR (simulating signal loss at multiple scales `pFHRn/pFHRd`), and **synthesizes false signals** by replacing FHR with MHR(+`DiffFM` offset) over random windows (modeling the Doppler-grabs-maternal-HR confusion) and flagging those samples false. `4 FSScalp.py` is the standalone (Google-Cloud TPU) version of the Scalp training with a simpler 4-feature input and analogous augmentation.
- Exported to `.mat` via `scipy.io.savemat` (cell 17). `.h5` files (`FSDop.h5`,`FSMHR.h5`,`FSScalp.h5`) are Keras weights.

### 5.4 Evaluation (`EvalFSForDataset.m`, `EvalFSAllDatasets.m`, `SaveFSAndEvalCustomModel.m`)
- `EvalFSForDataset(model,stage,dataset,censorMHR)`: loads `FSdataset/expertAnnotations.mat` `DB`; per recording opens `.fhrm`, builds `isStage2` from `DB(i).Stage2_Start`, runs the model (or loads precomputed probs from a `.mat` with cell `PDop/PScalp/PMHR{filename,probs}`); compares P≥0.5 vs expert true/false selections (`TS_*`/`FS_*`, sample ranges). Builds `Truth` (1=false-region per FS_*, 0=true per TS_*, 0.5=unannotated/ignored), per-sample weights `sqrt(len/#annotated)`, and computes Sensitivity/Specificity/PPV/NPV/Accuracy/AUC/(weighted)CrossEntropy via contingency table. `stage`: 0=all, 1=first, 2=second, -1=antepartum. `censorMHR` zeros MHR to test FSDop without MHR.
- `EvalFSAllDatasets`: runs a matrix of (model,stage,dataset,withMHR) configs, tabulates.
- `SaveFSAndEvalCustomModel`: template to run YOUR model over all Dop files, save `MyFSDopMethodAnalysis.mat` (`PDop{name,probs}`), then re-evaluate to confirm encoding.
- `showFSAnalysis(file,chan,Stage2Start)`: GUI single-file viewer.

---

## 6. DATASETS

### 6.1 FHRMA morphological-analysis dataset (`FHRMAdataset/`)
- `traindata/train01..66.fhr` (66 files), `testdata/test01..90.fhr` (90 files). `.fhr` format (section 1.1), 4 Hz, FHR1/FHR2/TOCO, no MHR. (~14000+ samples each ≈ 1 hour.)
- `analyses/expertAnalyses.mat`: struct array `data` `1×156` (66 train + 90 test). Fields per record:
  - `filename` (e.g. `'train01.fhr'`)
  - `expertPts` `2×k`: expert baseline control points `[time_in_minutes; bpm]` (linearly interpolated → `baseline` via `linearinterpolation(BL(1,:)*240, BL(2,:), 1:len)`).
  - `baseline` `1×len`: full 4-Hz expert baseline (consensus).
  - `accelerations`,`decelerations`,`overshoots`,`unreliableSignal`,`notToAnalyse`: each `n×2` interval lists in **minutes** `[start end]`.
  - `trainingData`: 1=train, 0=test (counts: 90 with value 0, 66 with value 1; ordering: tests first then trains in the array).
- Other `*_std.mat`/`*_orig.mat` in `analyses/` = saved per-method results (W=Wrobel, L=Lu, C=Cazares, H=Houze, J=Jimenez, T=Taylor, A=Ayres, MD=Maeda, MG=Mongelli, MT=Mantel, P=Pardey, WMFB). `WMFB_orig.mat` = WMFB results. Only needed as comparison references.

### 6.2 FS dataset (`FSdataset/`)
- `DopMHR/` (Doppler+MHR `.fhrm`, 12-byte format): `Train/` 591, `Val/` 142, `TestCurrentPractice/` 30, `TestDoubleSignals/` 45 files.
- `ScalpECG/`: `Train/` 188, `Val/` 39, `Test/` 30 (scalp ECG `.fhrm`; FHR2 = scalp channel).
- `expertAnnotations.mat`: struct array `DB` `1×1065`. Fields:
  - `filename` (e.g. `'DopMHRTrain0001.fhrm'`), `dataset` (one of `DopMHRTrain/DopMHRVal/DopMHRTestCP/DopMHRTestDbS/ScalpTrain/ScalpVal/ScalpTest`; counts: 591/142/30/45/188/39/30).
  - `TS_FHR`,`FS_FHR`,`TS_MHR`,`FS_MHR`: `n×2` **sample-index** ranges (4 Hz) of expert True-Signal / False-Signal selections for the FHR and MHR channels.
  - `Stage2_Start`: int sample index where 2nd stage begins, or `'Antepartum'` string, or empty (no 2nd stage).
  - `Comment`.
  - Test datasets (`TestCP`/`TestDbS`/`ScalpTest`) have empty labels (held out).

### 6.3 Examples (`Examples/`)
11 `.fhrm` recordings (named `Example N Doppler ... Stage 2 at min M.fhrm`), Doppler+MHR, for demoing FS detection (mostly 2nd-stage with MHR/FHR confusion). Larger files (~0.7 MB ≈ many minutes). No label file; `Stage2_Start` is encoded in the filename ("at min M").

---

## 7. `multisigfilter.c` — zero-phase (filtfilt) multi-channel filter

A hand-written, multi-threaded reimplementation of MATLAB `filtfilt` for the IIR filter `(b,a)` of given `order` (length of b = order). It is functionally equivalent to `scipy.signal.filtfilt(b, a, x, axis=0, padtype='odd', padlen=nfact)` applied independently to each column, with `nfact = 3*(order-1)`.

### 7.1 Interface
`fdata = multisigfilter(b, a, data, zi [, processMax])`
- `b`,`a`: filter coeffs (row vectors, length `order`).
- `data`: `samples × nchan` (each **column** = one channel).
- `zi`: initial-condition vector (length `order-1`), precomputed in `butterfilt.m` by solving the sparse system (the standard `filtfilt` `zi` from `lfilter_zi`).
- `processMax`: thread count (default 2). Threads pull channel indices via an atomic counter `++(*chancount)` and each runs `filter()` on one channel — embarrassingly parallel over channels. For NumPy: vectorize over the channel axis, or use joblib/multiprocessing; correctness does not depend on threading.

### 7.2 Per-channel `filter()` (forward-backward with odd reflection padding)
For a channel `data[0..samples-1]`:
1. `nfact = 3*(order-1)`. Allocate `d[samples+nfact]`, `dinit[nfact]`.
2. **Odd (point-symmetric) reflection at the start**: virtual samples for i<0 are `2*data[0] - data[-i]` (reflection through the first point). Initialize the filter state from `zi` scaled by `2*data[0]-data[nfact]` (the standard `filtfilt` edge handling: `x_edge = 2*x[0]-x[nfact:0:-1]`, state = `zi*x[0]`-equivalent), then run the **forward** Direct-Form-II-transposed difference equation through the left pad into the real signal:
   - difference eq used (lines 149-155): `d[i] = b[0]*data[i] + Σ_{j=1..order-1}( b[j]*data[i-j] - a[j]*d[i-j] )`.
   - left-edge (lines 123-144) and right-edge (lines 157-168, virtual `2*data[samples-1]-data[2*samples-2-i]`) use the reflected virtual samples.
3. **Backward pass** over `d` (lines 170-198): same difference equation run in reverse order into `fdata`, again seeding from reflected right-edge via `zi` (`dinit[i-samples]=d[last]*zi[...]`). Result `fdata[i]` = the zero-phase filtered channel.

The two passes (forward then backward) cancel phase. Edge transients are minimized by the `3*(order-1)`-length odd reflection on both ends, exactly as MATLAB `filtfilt`. The state `zi` ensures the step-response starts settled.

### 7.3 Port recommendation
- **Simplest exact-enough**: `scipy.signal.filtfilt(b, a, x, padtype='odd', padlen=3*(order-1))` per channel (vectorize: `filtfilt(b,a,X,axis=0)`). This matches MATLAB `filtfilt` and hence this MEX to within floating-point tolerance.
- **Bit-exact / Rust multi-core**: reimplement the two-pass DF-II-transposed recursion above with odd reflection of length `nfact=3*(order-1)` and the `zi` seeding from `butterfilt`. Parallelize over the channel axis (each channel independent), exactly as the C threadpool does. The math in §7.2 is the full spec.

---

## 8. PORT ORDER / DEPENDENCY NOTES
1. `fhropen`/`fhrsave` (file I/O) — trivial NumPy `frombuffer` with the dual-view trick.
2. `butterfilt` + the filtfilt core (§7) — foundation for everything DSP.
3. `preprocess` chain: `removesmallpart`, `interpolFHR`, helpers.
4. `aamwmfb` + `medgliss` + `enveloppe` + accident helpers — the baseline (needs MATLAB-matching `interp`/`decimate`; use `scipy.signal.resample_poly`/`decimate` or reimplement the FIR).
5. `validaccident`/`simpleaddetection`/`startendlist` — A/D detection.
6. `statscompare`/`evaluateaam` — evaluation (optional, for validation against `expertAnalyses.mat`).
7. FS inference: reimplement `GRU`/`Dense`/bidir wiring (§5.2) in NumPy, load weights from `FSDop.mat`/`FSScalp.mat` (cell arrays → list of arrays via `scipy.io.loadmat`). No TF needed for inference.
8. Validate WMFB against `WMFB_orig.mat` (MADI median) and FS against `EvalFSForDataset` numbers.

### Constants quick-reference
- Sample rate 4 Hz; many DSP calls pass `srate=240` (=4×60, freqs in cycles/min).
- HR range clip 50–220 bpm; missing=0.
- WMFB: LP cutoffs fc∈{1,2,4,8,16} (order-1 zero-phase); band features fcut=[0 1 3 7]; logistic Q=[-2.4744,0.0266,0.0413,0.0105,0.0036]; distancecoef len 401 triangular; decim=24; 6 passes; attraction biases {3.21,2.5,2.0,1.5,1.0}, slope 0.19, c=0.1.
- A/D thresholds: candidate dev 5 bpm; valid duration ≥15 s, amplitude ≥15 bpm; small-event 5-bpm.
- FS: feature norm `(hr-120)/60`; decision threshold P=0.5; scalp hold = ≥12 identical samples.
- Annotation time bases: FHRMA expert intervals in **minutes**; FS `TS_/FS_` in **samples** (4 Hz); `unreliableSignal` arg to preprocess in **minutes** (×240).
