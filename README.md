# PSTBSK-X Ver 0.14

PSTBSK-Xは、**TBSKmodemを利用してアマチュア無線でTBSK通信を楽しむためのWindows向け通信ソフトウェア**です。
Python / PySide6で開発しています。

WSJT-X / JTDXのように受信した信号を見つけて交信対象を選びつつ、TBSKの特徴を生かして、固定タイムスロットに縛られない通信やUTF-8自由文通信を扱えるソフトを目指しています。

PSTBSK-X同士の通信には**CRC付きPTX1フレーム**を使用します。また、Web版などから送信された生UTF-8 TBSKについても受信し、受信欄に`[TBSK RAW]`として表示します。

---

## TBSKとは

**TBSK（Trait Block Shift Keying）**は、nyatla氏によって開発された、PCM音声信号を利用してデジタルデータを伝送する変調方式です。

TBSKでは、特徴を持つ一定長のトーン波形とその反転波形を用いてデータを表現し、隣接する信号ブロック間の相関を利用して復調します。FFT/IFFTを前提とせず、ビット／バイト列とPCM信号を相互に変換できることが特徴です。

TBSKそのものはアマチュア無線専用の方式ではありません。PSTBSK-Xでは、このTBSKをアマチュア無線の音声帯域で扱いやすくするためのUI、通信フレーム、交信操作、ログなどを上位層として組み合わせています。

## TBSKmodemとは

**TBSKmodem**は、TBSKによる変復調を実装したオープンソースのソフトウェアモデムライブラリです。

PSTBSK-XはTBSKmodemを変復調エンジンとして利用する**独立したアプリケーション**であり、TBSKmodemのForkではありません。

- TBSKmodem GitHub: https://github.com/nyatla/TBSKmodem
- License: MIT License
- 同梱ライセンス: `licenses/TBSKmodem_LICENSE.txt`

TBSKmodemが主に変復調を担当し、PSTBSK-X側ではPTX1フレーム、CRC、受信表示、交信操作、ログなどアマチュア無線で使用するための上位機能を扱います。

---

## PSTBSK-Xの通信

### PTX1フレーム

PSTBSK-X同士の通信では、CRC付きの**PTX1フレーム**を使用します。

CRCにより、復調されたデータが正常なフレームとして受信できたかを確認できるようにしています。

### TBSK RAW受信

PSTBSK-X独自のPTX1フレームだけでなく、Web版などから送信された**生UTF-8 TBSK**も受信できます。

正常にデコードされたRAW通信は、受信欄に次のように表示します。

```text
[TBSK RAW]
```

RAW行は現在**表示用**です。Ver 0.14では、RAW行をダブルクリックしても交信シーケンスには取り込みません。

PSTBSK-XのPTX1フレームとして受信した行は、相手局が識別できる場合にダブルクリックして交信対象として選択できます。

### UTF-8

文字データにはUTF-8を使用するため、英数字だけでなく**日本語を含む自由文**も扱える設計です。

---

## PSTBSK-Xが目指す操作感

PSTBSK-Xでは、TBSK通信を「モデムの実験」だけで終わらせず、通常のアマチュア無線交信として楽しめる操作感を目指しています。

主な方向性は次のとおりです。

- 音声帯域内のTBSK信号を受信・デコード
- 受信結果から交信相手を選択
- S/Nを利用したレポート交換
- 定型シーケンスと自由文を組み合わせたQSO
- UTF-8による日本語自由文通信
- CAT / PTTとの連携
- QSO結果のADIFログ記録

FT8のような15秒固定スロットを前提とせず、TBSKフレームを受信したタイミングで順次デコードして扱う方向です。

> この節にはPSTBSK-Xの開発方針・目標を含みます。Ver 0.14ですべての機能が完成していることを示すものではありません。現在確認済みの範囲は下記を参照してください。

---

## Windowsでビルド

### 必要環境

- Windows
- Python 3.12
- PowerShell

このフォルダーで次を実行します。

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
.\build-windows.ps1
```

`build-windows.ps1`はテストとPyInstallerビルドを実行し、次のWindows配布ZIPを生成します。

```text
release/PSTBSK-X_0.14_win64.zip
```

配布用ZIPの中は次の構成です。

```text
PSTBSK-X.exe
config/
log/
bak/
licenses/
```

PyInstallerで必要なPythonランタイム等を同梱するため、配布版は**PythonがインストールされていないWindows環境でも実行できる構成**を想定しています。

既存環境を更新する場合は、`config/`、`log/`、`bak/`を保持してください。

アプリ内バージョンアップには、このソースZIPではなく**Windows配布ZIP**を指定します。

---

## 確認済みの範囲

Ver 0.14では、開発環境で**41件の単体テストと構文検査を通過**しています。

また、ユーザーのWindows実機で、**ステレオミキサー入力からWeb版TBSK 1600 HzのCQ全文が`[TBSK RAW]`として表示されることを確認**しています。

現時点でのRAW受信については、次の制限があります。

- RAW行は表示用
- RAW行のダブルクリックでは交信シーケンスへ取り込まない
- PSTBSK-XのPTX1フレームとして受信した行は、相手局を識別できる場合に交信対象として選択可能

---

## アマチュア無線での使用について

PSTBSK-XはTBSKによるデータ通信を行うソフトウェアです。

実際に電波を送信する際は、各自の免許内容、使用する電波型式、周波数の使用区別、最新のアマチュアバンドプラン等を確認し、データ通信が可能な周波数で運用してください。

---

## ライセンス / クレジット

### PSTBSK-X

PS Ham-ware / AKIHABARA-GIKEN / JH1HST

### TBSKmodem

PSTBSK-Xは**TBSKmodem by nyatla**を利用しています。

TBSKmodemはMIT Licenseで提供されています。

- Project: https://github.com/nyatla/TBSKmodem
- License file: `licenses/TBSKmodem_LICENSE.txt`

PSTBSK-XとTBSKmodemは別プロジェクトです。PSTBSK-XはTBSKmodemのForkではなく、TBSKmodemを利用する独立したアプリケーションです。

---

## バージョン

Current version: **PSTBSK-X Ver 0.14**
