# Verifikasi pipeline training TFT/LSTM (RO2)

Dokumen ini merangkum hasil tinjauan kebenaran (logic, API neuralforecast, metodologi
statistik, dan kesesuaian terhadap requirement pipeline) atas kode training/inferensi
DO forecasting. Tinjauan dilakukan terhadap kode pada repositori KJA Digital Twin
(bukan terhadap hasil metrik model pada data lapangan).

Tujuan: memastikan klaim metodologis Bab 3/4 (RO2) selaras dengan implementasi,
sebelum hasil eksperimen dipakai sebagai temuan empiris.

## Cakupan berkas

- `training/preprocess.py`
- `training/pipeline.py`
- `training/train_tft.py`
- `training/train_lstm.py`
- `training/evaluate.py`
- `training/ablation_encoder_length.py`
- `training/generate_synthetic_dataset.py`
- `inference/tft_model.py`
- `api/sensors.py` (dua call site `predict_do`)

## Requirement yang diuji

1. Split train/val/test 70/15/15 berdasarkan waktu per seri, tanpa pengacakan.
2. R², RMSE, MAPE dihitung dan dilaporkan terpisah per horizon (+6h, +24h, +7d).
3. Walk-forward evaluation tidak membocorkan informasi setelah origin ke encoder.
4. Peran fitur sesuai dekomposisi ŷ(q,t,τ)=f_q(τ, y, z, x, s): target y,
   hist_exog z, futr_exog x, static s; `futr_df` lengkap saat predict.
5. Validasi volume minimum: porsi train ≥ encoder_length + max_horizon.
6. `predict_do()` tidak menjatuhkan API jika artifact hilang atau inferensi gagal.
7. Generator data sintetis menurunkan durasi dari `min_series_hours()` dan
   mencukupi encoder ablation terbesar (504 jam).
8. Edge case dan fallback diam yang dapat menyembunyikan bug.

Skala temuan: **bug** (perlu diperbaiki sebelum klaim RO2), **risiko**
(dokumentasikan atau perbaiki), **lulus**.

## Hasil per requirement

### 1. Split kronologis 70/15/15 — lulus, dua risiko (satu diperbaiki)

`chronological_split` memotong per `unique_id` setelah sort `ds`, tanpa shuffle.
Sisa pembulatan `int()` masuk test. `nf.fit` hanya menerima concat train+val.

Risiko yang diperbaiki: concat `history` kini di-sort `unique_id, ds` sebelum
`nf.fit`.

Risiko tersisa: `val_size` global = min panjang val antar seri, sehingga rasio
15% tidak seragam jika panjang seri berbeda. Bukan kebocoran test.

### 2. Metrik per horizon — lulus

Tabel perbandingan tidak merata-ratakan antar horizon. Ablation juga mengurutkan
per horizon. Catatan: `confidence` di API adalah `1 − mean(MAPE)` lintas horizon;
itu metrik produk dashboard, bukan baris tabel Bab 4.

### 3. Walk-forward / kebocoran encoder — tidak ada kebocoran y masa depan

Encoder: `window = series[ds <= origin].tail(encoder_length)`. Target dan `futr_df`
berada pada `origin+1h … origin+h`. Origin di dalam test boleh memakai aktual test
yang sudah terjadi (walk-forward operasional).

Bug yang diperbaiki: resample tidak lagi membuang jam kosong lalu memakai N
observasi sebagai pengganti N jam kalender. Grid jam-an dilengkapi; lubang yang
tidak terisi dalam 3 jam ditolak. Origin walk-forward memakai timestamp terakhir
porsi history (bukan `test_start − 1h`).

Risiko tersisa: semua origin disyaratkan cukup untuk h=168, sehingga sampel
+6h/+24h lebih sedikit dari yang seharusnya.

### 4. Peran y/z/x/s dan futr_df — sebagian besar benar

- y = `do_observed` → kolom `y`
- z = pH, suhu, salinitas, kekeruhan, cahaya → `hist_exog_list` (TFT dan LSTM)
- x = `rainfall_forecast_mm` → `futr_exog_list`; `futr_df` dibangun untuk +1…+h
- s = `species` jika ada di CSV; `kja_id` hanya `unique_id` (bukan `stat_exog`)

TFT tidak mendapat embedding `kja_id` sebagai kovariat statis; identitas keramba
hanya lewat pemisahan seri.

Bug yang diperbaiki: kegagalan `predict` pada walk-forward di-log (`logger.exception`)
dan dihitung; tidak lagi `except Exception: continue` tanpa jejak. Inferensi
produksi menyeleksi horizon lewat cocokan `ds` (sama seperti evaluasi), dengan
fallback posisi jika timestamp tidak ketemu. Jika `tft_v1_meta.json` absen,
kovariat default ke `HIST_EXOG` / `FUTR_EXOG` yang ada di frame.

Risiko tersisa: hujan pada baris `t+τ` di evaluasi adalah nilai yang tersimpan
pada timestamp itu (sah jika kolom itu prakiraan yang tersedia di origin).

### 5. Validasi volume — aritmetika train benar; jaminan test ditambahkan

`min_series_hours` sekarang `max(ceil((encoder+h)/0.70), ceil(h/0.15))` sehingga
porsi test 15% juga ≥ max_horizon (168 jam). Dataset yang hanya lolos ambang train
720 jam (tanpa cukup test untuk +7d) kini ditolak.

### 6. Ketahanan API — lulus

`predict_do()` selalu mengembalikan kontrak (`do_now`, `do_6h`, `do_24h`, `do_7d`,
`confidence`, `latency_ms`, opsional `error`). Ingest: HTTP 503 jika prediksi
tidak tersedia. GET inferensi: 200 + field null/error (tidak crash).

### 7. Dataset sintetis vs ablation 504 — lulus untuk default; sumber konstanta disatukan

Kandidat encoder ablation `(168, 336, 504)` didefinisikan sekali di
`preprocess.ABLATION_ENCODER_LENGTHS`. Generator memakai
`min_series_hours(max(ABLATION_ENCODER_LENGTHS), max(HORIZONS))`. Perubahan
`HORIZONS` atau tuple ablation ikut ke durasi sintetis.

`--hours` manual pada generator tetap dapat merusak jaminan jika dipaksa lebih
pendek.

Generator tidak menulis `species`; `stat_exog` kosong pada data uji pipeline
(boleh untuk tes kode, bukan untuk klaim s_i di tesis).

### 8. Edge case

Ditangani: satu `kja_id`; n terlalu kecil ditolak volume check; timestamp tidak
monoton di-sort; duplikat di-drop (`keep=last`) dan di-log; deret jam-an tidak
rapat ditolak; kegagalan walk-forward di-log.

Limitasi: `confidence=0.0` jika file metrik absen; hujan absen di produksi
diulang nilai terakhir (atau 0,0) sebagai placeholder BMKG; `do_now` produksi
bersumber dari histori `do_predicted`.

## Perbaikan setelah tinjauan

Diterapkan pada kode setelah audit di atas:

1. Walk-forward: log exception + hitungan origin gagal (`training/evaluate.py`).
2. Resample: reindex grid jam-an lengkap; tolak lubang yang tidak terisi
   (`training/preprocess.py`).
3. `min_series_hours` menjamin test ≥ max_horizon.
4. `history` di-sort sebelum `nf.fit` (`training/pipeline.py`).
5. `ABLATION_ENCODER_LENGTHS` bersama untuk ablation dan generator.
6. `predict_do`: seleksi horizon by `ds`; fallback kovariat jika meta hilang.

## Ringkasan untuk penulisan tesis

Implementasi **selaras** dengan klaim utama RO2: split waktu 70/15/15, metrik
per horizon, dekomposisi y/z/x pada TFT dan baseline LSTM, `futr_df` untuk
horizon penuh, dan inferensi yang gagal secara eksplisit.

Limitasi metodologis yang wajar dicantumkan: `kja_id` bukan kovariat statis;
`do_now` produksi bersumber dari histori `do_predicted`; `confidence` dashboard
merata-ratakan MAPE; origin walk-forward untuk +6h/+24h masih terikat panjang
horizon +7d.
