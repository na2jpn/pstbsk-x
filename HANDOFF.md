# PSTBSK-X Ver 0.16 引き継ぎ

## 基準

この正本ZIPがVer 0.16の唯一のソース基準です。以前の正本・差分を再適用しないでください。ソース版番号は`pstbskx/__init__.py`、配布ZIPのファイル名は`windows.ps1`が版番号から生成します。

## 0.16 ライセンス画面と署名

- ヘルプの順番は運用上の注意、ウィンドウ位置リセット、バージョンアップ、ライセンス、PSTBSK-Xについて。独立したライセンス画面で本体GPL全文、共通ライセンス説明、Ryo Iizuka（nyatla）氏のTBSKmodem MIT原文をオフラインで表示する。About画面も著作者表示を保持する。
- 公開Gitの`LICENSE.md`、`LICENSING.md`、`licenses/TBSKmodem_LICENSE.txt`を継承し、Windows配布ZIPに同梱。第三者の著作者表示を本体の著作者表示と混同しない。
- Windowsビルドは`windows.ps1`。証明書拇印を明示してEXEを署名・タイムスタンプ・検証してから、更新用マニフェストで署名済みEXEのハッシュを記録する。署名失敗時に配布ZIPは作らない。詳しくは`SIGNING.md`。旧`build-windows.ps1`は互換入口。
- Windows証明書・SignToolがこのLinux開発環境にないため、Windows実機署名と更新適用の確認は未実施。

## 狭帯域送信

- 送信はTBSKmodemのSinTone(32,24)、48 kHz、62.5 bps、固定中心1500 Hz、CRC付きPTX1フレームです。AutoCQ・シーケンス・自由文すべてに適用します。
- 以前の`pstbskx_150`、`web_160`設定は送信に使用せず、0.15で狭帯域へ移行。Webおよび旧XPskSin波形は受信専用。Web素文は`[TBSK RAW]`表示のみでQSO・ADIFへ入りません。
- 各送信前にPCMの99%電力帯域幅を検査し、1.5 kHzを超えればPTT前に中止。成功時の幅はステータスバーに表示します。RFの占有帯域幅は実機で別途測定し、3 kHz未満を確認してください。詳細は`AUDIO_BANDWIDTH_0.15.md`。
- Ver 0.14のWeb受信実機結果は継承します。Ver 0.15のWindows配布ビルド、無線機接続、RF送信・測定は未検証です。

## 受信・ログ

PSTBSK-XのPTX1受信行は送信元CALLが識別できる場合にダブルクリックで交信対象へ反映します。行選択だけで送信は開始しません。ログは`log/tbskx.adi`で、バックアップは`bak/`へ保存します。

## 検証と次版

Linuxで`python -m unittest discover -s tests -q`の47件と`python -m compileall -q main.py pstbskx tests`を確認しました。新トーンの合成PCMを同じ受信器でPTX1として復調し、送信前の帯域検査も確認しました。次の変更はユーザーの明確な実装指示を待ちます。
