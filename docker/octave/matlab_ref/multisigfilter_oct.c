// Portable (Linux/Octave) build of multisigfilter.c for the FHRPY parity harness.
//
// The upstream multisigfilter.c (kept verbatim in this folder as a reference)
// uses <windows.h> / _beginthreadex and only ships as Windows .mexw32/.mexw64
// binaries, so it cannot be compiled by mkoctfile on Linux. This file is a
// LINE-FOR-LINE copy of the numerical filter() routine from multisigfilter.c
// with the Windows multithreading wrapper replaced by a trivial sequential loop
// over channels. The per-channel arithmetic (the part FHRPY ports in
// fhrpy/preprocess/dsp.py::_filter_channel) is byte-for-byte identical.
//
// Build (done automatically by run_reference.m):
//     mkoctfile multisigfilter_oct.c -o multisigfilter.oct
//
// Octave then resolves multisigfilter(b,a,data,zi[,nproc]) to this .oct, so
// butterfilt.m uses the ORIGINAL C filtering path (not the filtfilt fallback).
//
// Provenance: derived from FHRMA toolbox multisigfilter.c (GPLv3,
// (C) 2018 Samuel Boudet). Used here only as a numerical parity reference.

#include "mex.h"
#include <math.h>
#include <stdlib.h>
#include <stdio.h>

#define MIN(a, b) (((a) < (b)) ? (a) : (b))
#define MAX(a, b) (((a) > (b)) ? (a) : (b))

void filter(double *fdata, double *data, int samples, double *b, double *a, int order, double *zi);

void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[]) {
    int samples, nchan, order;
    double *fdata, *data, *a, *b, *zi;
    int n;

    if (nrhs != 4 && nrhs != 5) {
        mexErrMsgTxt("Incorrect number of input arguments");
    }
    samples = ((int) mxGetM(prhs[2]));
    nchan = ((int) mxGetN(prhs[2]));
    order = ((int) mxGetN(prhs[0]));

    if (mxIsComplex(prhs[0]) || mxIsComplex(prhs[1]) || mxIsComplex(prhs[2])) {
        mexErrMsgTxt("Complex values are not supported");
    }
    if (!mxIsDouble(prhs[0]) || !mxIsDouble(prhs[1]) || !mxIsDouble(prhs[2]))
        mexErrMsgTxt("Only double values are supported");

    b = mxGetPr(prhs[0]);
    a = mxGetPr(prhs[1]);
    data = mxGetPr(prhs[2]);
    zi = mxGetPr(prhs[3]);

    plhs[0] = mxCreateDoubleMatrix(samples, nchan, mxREAL);
    fdata = mxGetPr(plhs[0]);

    // Sequential over channels (replaces the Windows thread pool).
    for (n = 0; n < nchan; n++) {
        filter(&fdata[n * samples], &data[n * samples], samples, b, a, order, zi);
    }
    return;
}

// ---- verbatim from multisigfilter.c ----------------------------------------
void filter(double *fdata, double *data, int samples, double *b, double *a, int order, double *zi) {
    double *d, *dinit;
    int i, j, nfact;
    nfact = 3 * (order - 1); // Prolongation for minimizing border effect
    d = malloc((samples + nfact) * sizeof(double));
    dinit = malloc(nfact * sizeof(double));
    //*****************First pass *************************
    //Initial values***************************************
    //data[i] (i>=0?data[i]:2*data[0]-data[-i])
    //d[i]= (i>=0?d[i]:dinit[nfact+i])

    for (i = 0; i < order - 1; i++)
        dinit[i] = (2 * data[0] - data[nfact]) * zi[i];
    for (i = order - 1; i < nfact; i++)
        dinit[i] = 0;

    for (i = -nfact; i < 0; i++) {
        for (j = MIN(order - 1, i + nfact); j >= 1; j--) {
            dinit[nfact + i] = b[j] * (2 * data[0] - data[-i + j]) + dinit[nfact + i] - a[j] * dinit[nfact + i - j];
        }
        dinit[nfact + i] += b[0] * (2 * data[0] - data[-i]);
    }

    for (i = 0; i < order - 1; i++) {
        d[i] = 0;
        for (j = order - 1; j > i && j >= 1; j--) {
            d[i] = b[j] * (2 * data[0] - data[-i + j]) + d[i] - a[j] * dinit[nfact + i - j];
        }
        for (j = i; j >= 1; j--) {
            d[i] = b[j] * data[i - j] + d[i] - a[j] * d[i - j];
        }
        d[i] += b[0] * data[i];
    }

    //Normal values***************************************
    for (i = order - 1; i < samples; i++) {
        d[i] = 0;
        for (j = order - 1; j >= 1; j--) {
            d[i] = b[j] * data[i - j] + d[i] - a[j] * d[i - j];
        }
        d[i] += b[0] * data[i];
    }

    //End values********************************************
    //data[i] (i<samples?data[i]:2*data[samples-1]-data[2*samples-2-i])
    for (i = samples; i < samples + nfact; i++) {
        d[i] = 0;
        for (j = order - 1; j > i - samples && j >= 1; j--) {
            d[i] = b[j] * data[i - j] + d[i] - a[j] * d[i - j];
        }
        for (j = MIN(order - 1, i - samples); j >= 1; j--) {
            d[i] = b[j] * (2 * data[samples - 1] - data[2 * samples - 2 - i + j]) + d[i] - a[j] * d[i - j];
        }
        d[i] += b[0] * (2 * data[samples - 1] - data[2 * samples - 2 - i]);
    }

    //***********Reverse order************************
    //init values ************************************
    for (i = samples + nfact - 1; i >= samples; i--) {
        if (samples + nfact - i < order)
            dinit[i - samples] = d[samples + nfact - 1] * zi[samples + nfact - i - 1];
        else
            dinit[i - samples] = 0;
        for (j = MIN(order - 1, nfact + samples - i - 1); j >= 1; j--) {
            dinit[i - samples] = b[j] * d[i + j] + dinit[i - samples] - a[j] * dinit[i - samples + j];
        }
        dinit[i - samples] += b[0] * d[i];
    }
    for (i = samples - 1; i > samples - order; i--) {
        for (j = order - 1; j >= samples - i && j >= 1; j--) {
            fdata[i] = b[j] * d[i + j] + fdata[i] - a[j] * dinit[i + j - samples];
        }
        for (j = samples - 1 - i; j >= 1; j--) {
            fdata[i] = b[j] * d[i + j] + fdata[i] - a[j] * fdata[i + j];
        }
        fdata[i] += b[0] * d[i];
    }

    //Normal values***************************************
    for (i = samples - order; i >= 0; i--) {
        for (j = order - 1; j >= 1; j--) {
            fdata[i] = b[j] * d[i + j] + fdata[i] - a[j] * fdata[i + j];
        }
        fdata[i] += b[0] * d[i];
    }
    free(d);
    free(dinit);
}
