# list_music_artist

Lista contendo nomes de artistas.

O Lidarr não importa artistas a partir de nomes soltos (JSON/texto) com precisão: ele precisa do **MusicBrainz Artist ID (MBID)** para evitar homônimos (ex.: "Leonardo").

## Duas formas recomendadas de importar no Lidarr

### 1) MusicBrainz List (recomendado para sincronização contínua)

1. Crie uma conta no MusicBrainz.
2. Crie uma **List** do tipo **Artists**.
3. Adicione os artistas nessa lista.
4. No Lidarr: **Settings → Lists → + → MusicBrainz List** e informe o **List ID** (UUID) da lista.

Vantagens: o Lidarr sincroniza periodicamente; você gerencia a lista no MusicBrainz.

### 2) Resolver MBIDs + importar via API do Lidarr (rápido e automatizável)

Fluxo:

1. Resolva os MBIDs a partir dos nomes do JSON com o script:
	- Python: `scripts/resolve_musicbrainz_ids.py`
	- PowerShell (recomendado no Windows quando há proxy/SSL corporativo): `scripts/resolve_musicbrainz_ids.ps1`
2. Use o CSV gerado para:
	- importar via script na **API do Lidarr** (`scripts/add_artists_to_lidarr.py`), ou
	- revisar manualmente os casos ambíguos e só então importar.

Observações importantes:

- A API do MusicBrainz exige `User-Agent` identificável e possui rate-limit; o script aplica espera e cache.
- Alguns nomes são ambíguos; o script gera um arquivo de “pendências” para revisão (ex.: nomes muito genéricos).

Exemplos:

- Resolver MBIDs (PowerShell):
	- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/resolve_musicbrainz_ids.ps1 -InputPath artistas_nacionais_rock_pop.json -Country BR -UserAgent "list_music_artist/1.0 (contact: you@example.com)"`
- Adicionar no Lidarr via API (dry-run):
	- `py -3 scripts/add_artists_to_lidarr.py --csv output/artists_with_mbid.csv --lidarr-url http://localhost:8686 --api-key <SUA_API_KEY> --root-folder "D:/Music" --quality-profile-id 1 --metadata-profile-id 1 --dry-run`

