# PSTBSK-X Ver 0.16

## ライセンス / License

Copyright (c) 2026 Hiroshi Tanaka (JH1HST)

PS Ham-ware / AKIHABARA-GIKEN — [開発者 / na2jpn](https://github.com/na2jpn)

PSTBSK-X本体は **GNU GPL v3以降（GPL-3.0-or-later）** で提供します。営利・非営利を問わず利用・改変・再配布できます。配布時はGPLに従って表示を保持し、対応するソースを提供してください。改良版の公開連絡は任意です。

- [ライセンス全文 / Full license](LICENSE.md)
- [共通方針・日英説明 / Licensing guide](LICENSING.md)
- [TBSKmodemのMITライセンス](licenses/TBSKmodem_LICENSE.txt)
- 公式サイト / Website: https://2jp.org/ps/
- ソースコード / Source code: https://github.com/na2jpn/pstbsk-x

PSTBSK-X is free software licensed under **GPL-3.0-or-later**. Third-party components retain their own licenses. TBSKmodem is by Ryo Iizuka / nyatla and remains under the MIT License; the common license does not relicense it.

Windows配布版は`licenses/LICENSE.md`と`licenses/LICENSING.md`を同梱し、ヘルプの独立した「ライセンス」画面からオフラインで確認できます。Python、PySide6/Qt、NumPy、sounddevice、pyserial、PyInstaller等の第三者コンポーネントの条件も個別に適用されます。

旧EXEの更新機能は配布ファイルを2個に固定して検査するため、共通文書を追加した新版への初回移行はアプリを閉じてWindows配布ZIPを上書き展開してください。新しい更新機能は従来の2ファイルZIPと共通文書付きZIPを検証し、設定・ログ・バックアップを保持します。


Python・PySide6によるWindows向けTBSK通信ソフトウェアのソース正本です。TBSKmodemで送受信し、PSTBSK-X同士の通信にはCRC付きPTX1フレームを使います。Web版などの生UTF-8 TBSKも受信欄に`[TBSK RAW]`として表示します。

## Windowsでビルド

Python 3.12を用意し、PowerShellでこのフォルダーから次を実行します。

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
.\windows.ps1 -CertificateThumbprint "<証明書のSHA-1拇印>"
```

`windows.ps1`はテスト・PyInstallerビルド・EXEの署名とタイムスタンプ・署名検証を実行し、`release/PSTBSK-X_0.16_win64.zip`を生成します。証明書を指定できない場合や署名・検証に失敗した場合は配布ZIPを作りません。Windows SDKのSignToolが必要です。旧`build-windows.ps1`は互換入口です。詳しくは`SIGNING.md`を参照してください。配布用ZIPの中は`PSTBSK-X.exe`と`config/`、`log/`、`bak/`、`licenses/`です。`licenses/`には本体のGPL全文・共通説明とTBSKmodemのMIT本文を同梱します。既存環境を更新する場合は設定・ログ・バックアップを保持してください。アプリ内バージョンアップにはこのソースZIPでなくWindows配布ZIPを指定します。

## 確認済みの範囲

Ver 0.16のLinux開発環境では47件の単体テストと構文検査を通過しました。Windows実機の署名・ビルドは未検証です。Ver 0.14では、ユーザーのWindows実機のステレオミキサー入力からWeb版TBSK 1600 HzのCQ全文が`[TBSK RAW]`として表示されました。

受信したRAW行は表示用です。現行版ではRAW行をダブルクリックしても交信シーケンスへは取り込みません。PSTBSK-XのPTX1フレームとして受信した行は、相手局が識別できる場合にダブルクリックで交信対象として選べます。

TBSKmodemのライセンスは`licenses/TBSKmodem_LICENSE.txt`を参照してください。

## Ver 0.15 狭帯域の送信

送信は48 kHz、SinTone(32,24)、62.5 bps、中心1500 Hzに固定。旧Web形式と旧XPskSin形式は受信専用です。従来の設定で起動しても送信は狭帯域に切り替わります。各送信の前に音声99%電力帯域幅を計算し、1.5 kHzを超えた場合はPTTをONにせず中止します。送信音の計測だけではRF占有帯域幅を確定できません。RF出力は適切なダミーロードで実測して3 kHz未満を確認してください。詳細は`AUDIO_BANDWIDTH_0.15.md`に記載します。0.15のWindows実機とRF送信は未検証です。
