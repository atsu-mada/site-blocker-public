# Site Blocker（日本語の説明）

Markdown の一覧に書いたサイトをブロックする Chrome 拡張機能です。`blockctl` コマンドとエージェント用のスキルが付いていて、**Claude Code** や **Codex** がブラウザを操作せずに、作業の間だけブロックをオフにし、終わったらオンに戻せます。

- **オフには必ず期限があります。** 時間が来ると自動でオンに戻るので、スクリプトやエージェントが途中で止まってもブロックは戻ります。
- **手でオフにするときは一呼吸おきます。** ツールバーのポップアップと操作ページは、10秒数えてからオフになります（「やめる」か Esc で取り消し）。最大30分です。
- **`blockctl` は Chrome の実際の状態を確かめます。** 拡張機能が Chrome の持っているブロック規則の数を報告し、`blockctl off` / `on` はその数で変化を確かめてから終了コード 0 を返します。
- **複数のセッションで使えます。** セッションごとにオフを持つので、先に終わったセッションの `on` が、ほかのセッションの作業中にブロックを戻すことはありません。
- **外へは何も送りません。** 拡張機能は Chrome のネイティブメッセージングでローカルのプログラムとだけ話します。ネットワークのポートは開きません。

英語の README（[README.md](../README.md)）が正本です。

## 必要なもの

- macOS か Linux と、Google Chrome 120 以降（Chromium・Brave・Edge でも動くはずです。確かめたのは macOS の Chrome だけです）。
- Python 3.9 以降（macOS に入っている `python3` で足ります）。追加のパッケージは要りません。
- スキルを使う場合は Claude Code か Codex。
- 任意: 拡張機能のテストに Node.js 18 以降、アイコンの作り直しに Pillow。

## 導入

### 1. コードを取得する

```bash
git clone https://github.com/atsu-mada/site-blocker-public.git
cd site-blocker-public
```

導入したあとはフォルダを動かさないでください。Chrome はホストのプログラムの絶対パスを覚えます。動かしたら手順3をやり直します。

### 2. 拡張機能を読み込む

1. `chrome://extensions` を開き、右上の「デベロッパーモード」をオンにする。
2. 「パッケージ化されていない拡張機能を読み込む」で `src/extension` フォルダを選ぶ。
3. カードに出る拡張機能の **ID**（32文字）を控える。ID はフォルダの場所から決まるので、フォルダを動かさなければ変わりません。

ホストを入れるまでは、`src/extension/default-sites.json` の短い一覧でブロックします。

### 3. ホストと `blockctl` を入れる

```bash
python3 src/host/install.py --extension-id <控えたID>
```

次のものが作られます。

| もの | 場所 |
| --- | --- |
| ネイティブメッセージングの登録（その ID の拡張機能だけを許可） | macOS は `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/local.site_blocker.host.json`、Linux は `~/.config/google-chrome/NativeMessagingHosts/` |
| ホストの設定（使う Python、一覧ファイル） | `~/.config/site-blocker/env` |
| ブロック一覧（無ければ `config/sites.example.md` からコピー） | `~/.config/site-blocker/sites.md` |
| `blockctl` | `~/.local/bin/blockctl`（このリポジトリへのリンク） |

オプション: `--browser chromium|brave|edge|chrome-beta`、別の一覧ファイルを使う `--list <パス>`（Obsidian の Vault 内のノートなど）、`--python <パス>`、`--bin-dir <フォルダ>`、`--hosts-dir <フォルダ>`（テスト用のプロフィール向け）、書き込まずに内容だけ出す `--dry-run`。`~/.local/bin` が `PATH` に入っているか確かめてください。

最後に `chrome://extensions` で Site Blocker のカードの再読み込みボタンを押すと、拡張機能がホストにつながります。

### 4. 確かめる

```bash
blockctl status
```

`"connected": true`、`"enabled": true` で、`active_rules` と `expected_rules` が同じなら成功です。一覧のサイトを開くと、黄色の STOP 画面が出ます。

### 5. スキルを入れる（任意）

スキルのフォルダを、使うクライアントのスキルフォルダにリンクして、新しいセッションを始めます。

**Claude Code**

```bash
ln -s "$PWD/src/skills/site-blocker-operator" ~/.claude/skills/site-blocker-operator
```

`/site-blocker-operator` で呼べます。ブロック中のサイトを開く作業から使わせることもできます。

**Codex**

```bash
ln -s "$PWD/src/skills/site-blocker-operator" ~/.codex/skills/site-blocker-operator
```

お使いの Codex が読むスキルフォルダ（`~/.codex/skills` か `~/.agents/skills`）を使ってください。`$site-blocker-operator` で呼べます。

初めて `blockctl` を動かすとき、クライアントが許可を求めることがあります。Chrome の作業を頼むたびに `off` と `on` の確認を省きたい場合は、ご自分の `CLAUDE.md` か `AGENTS.md` にそう書いてください。

## 使い方

### ブロック一覧

`~/.config/site-blocker/sites.md`（または `--list` で指定したファイル）を編集します。ホストが2秒ごとに読み、変わったら拡張機能へ送ります。読むのは「**Blocked sites**」か「**ブロックするサイト**」という見出しの下の箇条書きだけで、次の見出しまでです。その見出しが無いファイルは全体を読みます。行頭の `> ` も使えるので、Obsidian のコールアウトの中に一覧を置けます。

| 書き方 | ブロックする範囲 |
| --- | --- |
| `- example.com` | `example.com` と `www.example.com` |
| `- *.example.com` | `example.com` とすべてのサブドメイン |
| `- example.com/path` | そのホストのそのパスから下だけ |

空白・`#`・`(` のあとはメモです。読めない行は飛ばして `list_errors` に出します。ファイルが無いか空のときは、前回読めた一覧を使い続けます。

### シェルやエージェントから

```bash
blockctl status            # Chrome がいま実際にしていることと、オフにしているセッション
blockctl off --for 20m     # 20分（既定）オフ。最大60分。時間が来ると自動でオン
blockctl on                # このセッションのオフを終える
blockctl on --all          # すべてのオフを終えて、すぐオンに戻す
```

どのコマンドも1行の JSON を出します。終了コードは、`0` が確認済み、`2` が20秒以内に確かめられない（Chrome が閉じている、拡張機能がつながっていない）、`3`（`status` だけ）がつながっていない、です。オフの持ち主は環境変数から読む Claude Code・Codex のセッション ID です。自分のスクリプトでは `--holder <名前>` か `SITE_BLOCKER_HOLDER` を指定します。

Chrome が閉じている間に頼んだオフは、次に Chrome が起動してホストがつながったときに反映されます。

### 手で操作する

- ツールバーのアイコン（ブロック中は朱色、オフの間は灰色）を押し、10・20・30分から選んでボタンを押します。10秒数えてからオフになります。
- 住所欄に `sb` と打って Enter を押すと、窓いっぱいの操作ページが開きます。`sb 10` で10分を選んだ状態になります。`chrome-extension://<拡張機能のID>/control.html` をブックマークしても開けます。
- 「今すぐオンに戻す」は、すべてのオフを終えてすぐにオンに戻します。
- ブロック画面には「← 戻る」と「タブを閉じる」だけを置いています。ここからブロックを外す方法はわざと作っておらず、ほかのサイトから操作ページは開けません。

## 仕組み

1. 拡張機能が起動すると、Chrome がホスト（`src/host/bin/site-blocker-host`）を起動し、標準入出力でやり取りします。
2. ホストは一覧ファイルとオフの状態（`~/.local/state/site-blocker/state.json`）を2秒ごとに確かめ、変わったときだけ拡張機能へ送ります。15秒ごとに状態の報告を求めます。
3. 拡張機能は一覧を `declarativeNetRequest` の動的ルールに変え、ページの読み込みをブロック画面へ転送します。オフの間はルールを全部外し、期限に `chrome.alarms` で戻します。
4. 拡張機能は Chrome が実際に持っているルールの数を報告し、ホストが `status.json` に書き、`blockctl` はその数を待ちます。
5. service worker が配るページのようにネットワークの読み込みが起きない場合に備え、`webNavigation.onCommitted` でも一覧と照らします。

実行時のファイルは `~/.local/state/site-blocker/`（`state.json`、`status.json`、`list-cache.json`、`host.log`）にあります。場所を変えるには `SITE_BLOCKER_STATE_DIR` を、環境変数か `~/.config/site-blocker/env` に書きます。

## 制限

- 自制のための道具で、セキュリティの境界ではありません。`chrome://extensions` で拡張機能を無効にすれば誰でも外せます。
- ブロックするのはページそのものの読み込みだけで、埋め込みのフレームやほかのサイトからのリクエストは止めません。
- シークレットウィンドウは、拡張機能に「シークレット モードでの実行を許可する」を付けない限りブロックされません。
- Chrome のプロフィールごとに拡張機能を読み込む必要があります。ホスト・一覧・オフの状態は全プロフィールで共通です。
- Windows には対応していません（ホストが `fcntl` とシェルの起動スクリプトを使うため）。
- デベロッパーモードで読み込む拡張機能で、Chrome ウェブストアにはありません。

## ライセンス

[MIT](../LICENSE)
