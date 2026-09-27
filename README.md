# PSTBSK-X Ver 0.15

Python・PySide6によるWindows向けTBSK通信ソフトウェアのソース正本です。TBSKmodemで送受信し、PSTBSK-X同士の通信にはCRC付きPTX1フレームを使います。Web版などの生UTF-8 TBSKも受信欄に`[TBSK RAW]`として表示します。

## Windowsでビルド

Python 3.12を用意し、PowerShellでこのフォルダーから次を実行します。

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
.\build-windows.ps1
```

`build-windows.ps1`はテストとPyInstallerビルドを実行し、`release/PSTBSK-X_0.15_win64.zip`を生成します。配布用ZIPの中は`PSTBSK-X.exe`と`config/`、`log/`、`bak/`、`licenses/`です。既存環境を更新する場合は設定・ログ・バックアップを保持してください。アプリ内バージョンアップにはこのソースZIPでなくWindows配布ZIPを指定します。

## 確認済みの範囲

開発環境で43件の単体テストと構文検査を通過しました。Ver 0.14では、ユーザーのWindows実機のステレオミキサー入力からWeb版TBSK 1600 HzのCQ全文が`[TBSK RAW]`として表示されました。

受信したRAW行は表示用です。現行版ではRAW行をダブルクリックしても交信シーケンスへは取り込みません。PSTBSK-XのPTX1フレームとして受信した行は、相手局が識別できる場合にダブルクリックで交信対象として選べます。

TBSKmodemのライセンスは`licenses/TBSKmodem_LICENSE.txt`を参照してください。

## Ver 0.15 狭帯域の送信

送信は48 kHz、SinTone(32,24)、62.5 bps、中心1500 Hzに固定。旧Web形式と旧XPskSin形式は受信専用です。従来の設定で起動しても送信は狭帯域に切り替わります。各送信の前に音声99%電力帯域幅を計算し、1.5 kHzを超えた場合はPTTをONにせず中止します。送信音の計測だけではRF占有帯域幅を確定できません。RF出力は適切なダミーロードで実測して3 kHz未満を確認してください。詳細は`AUDIO_BANDWIDTH_0.15.md`に記載します。0.15のWindows実機とRF送信は未検証です。
