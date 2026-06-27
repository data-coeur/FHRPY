function data = extractAccDecDataAmnio(events, FHRi, BL, type)
% EXTRACTACCDECDATAAMNIO Extrait les caractéristiques des acc/dec
%
% Entrées:
%   events - Matrice 2xN [début; fin] en secondes
%   FHRi   - Signal FHR interpolé
%   BL     - Baseline
%   type   - 'acc' ou 'dec'
%
% Sortie:
%   data   - Structure avec duration, amplitude, surface, nadir, slope

    n = size(events, 2);
    data.duration = zeros(1, n);
    data.amplitude = zeros(1, n);
    data.surface = zeros(1, n);
    data.surfaceDA2 = zeros(1, n);
    data.surfaceDA15 = zeros(1, n);
    data.nadir = zeros(1, n);
    data.slope = zeros(1, n);
    
    for i = 1:n
        s = max(1, round(events(1, i) * 4));
        e = min(length(FHRi), round(events(2, i) * 4));
        
        data.duration(i) = events(2, i) - events(1, i);
        
        if s < e && e <= length(FHRi) && e <= length(BL)
            if strcmp(type, 'dec')
                sig = BL(s:e) - FHRi(s:e);
                data.amplitude(i) = max(sig);
                data.surface(i) = sum(sig) / 240;
                data.surfaceDA2(i) = sum(sig.^2) / 240;
                data.surfaceDA15(i) = sum(max(sig, 0).^1.5) / 240;
                [data.nadir(i), idx] = min(FHRi(s:e));
                data.slope(i) = idx / 4;
            else
                sig = FHRi(s:e) - BL(s:e);
                [data.amplitude(i), idx] = max(sig);
                data.surface(i) = sum(sig) / 240;
                data.surfaceDA2(i) = sum(sig.^2) / 240;
                data.surfaceDA15(i) = sum(max(sig, 0).^1.5) / 240;
                data.nadir(i) = NaN;
                data.slope(i) = idx / 4;
            end
        end
    end
end
