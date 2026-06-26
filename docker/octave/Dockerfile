# Octave parity harness for FHRPY.
#
# Runs the ORIGINAL FHRMA MATLAB .m sources (copied into matlab_ref/) under
# GNU Octave, so the NumPy ports in fhrpy/ can be checked for numerical parity.
#
# We pin a concrete Octave version for reproducibility and install the Octave
# Forge `signal` package (needed by butterfilt.m -> butter, and by aamwmfb.m ->
# decimate/interp) plus its `control` dependency at build time, so the image is
# fully self-contained and does not hit the network at run time.
FROM gnuoctave/octave:9.2.0

# Octave Forge packages are installed at build time. `control` is a hard
# dependency of `signal`. Versions are whatever Forge serves at build time; the
# image is the reproducibility anchor (rebuild + commit the image digest if you
# need to freeze it further).
RUN octave --eval "pkg install -forge control" \
 && octave --eval "pkg install -forge signal" \
 && octave --eval "pkg load signal; disp('signal package OK')"

# A C compiler + mkoctfile already ship in the gnuoctave image; verify mkoctfile
# is on PATH so the multisigfilter build in run_reference.m cannot silently skip.
RUN which mkoctfile

WORKDIR /work
# The repo and matlab_ref are bind-mounted by docker-compose at run time
# (see docker-compose.yml). Nothing application-specific is COPYed in, so the
# same image works as you edit the harness scripts on the host.
CMD ["octave", "--no-gui", "--eval", "run('/opt/harness/run_reference.m')"]
