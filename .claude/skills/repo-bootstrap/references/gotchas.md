# 地雷庫

各 repo 實際踩過的。建骨架時只搬「新 repo 必定會遇到」的進 AGENTS.md〈Known Gotchas〉，附 before/after 與來源。

## 雲端 session

- **雲端驗證 image**（sol-pi、tuning-log）：沙箱連不到 `deb.debian.org`、TLS 被攔截、ghcr blob 被擋。
  用暫存副本（放 `.superpowers/`）拿掉 apt、注入 `/root/.ccr/ca-bundle.crt`（`--build-context ca=…`，
  `SSL_CERT_FILE`／`PIP_CERT`／`NODE_EXTRA_CA_CERTS`／`npm_config_cafile`）、`--network host`、proxy build-arg。
  正式 Dockerfile 不放 CA 與 proxy。uv 用 `pip install uv==<版本>`，不用 `COPY --from=ghcr.io/astral-sh/uv`。
- **dockerd**：`sudo setsid nohup dockerd > /tmp/dockerd.log 2>&1 &`，否則隨 shell 結束。
- **雲端是 root**：權限問題測不出來。驗證權限相關修改時，用加入 docker 群組的一般使用者 `sudo -u` 跑一次（sol-pi）。

## Docker

- **heredoc 要 `-i`**（tuning-log）：`docker run --rm image python - <<'PY'` 沒 `-i` → 什麼都沒跑、exit 0。檢查要看輸出內容。
- **容器寫 bind mount 的檔案屬 root**（sol-pi、log-analysis）：`docker run --user "$(id -u):$(id -g)"`。
- **改了程式碼不重 build 不生效**（log-analysis）：`exec`／`run` 開新 process 讀到掛載的新碼，會誤以為生效。
  驗收前 `build` ＋ `up -d --force-recreate`，並確認 `StartedAt` 晚於改檔時間。
- **Docker 網段吃掉廠內網段**（log-analysis）：compose 固定 `DOCKER_SUBNET`（198.18.0.0/24）；主機與容器各測一次連線。
- **`pg_dump` 經 `compose exec` 輸出到檔案要 `-T`**（tuning-log）：否則 TTY 改寫二進位輸出，還原時才失敗。
- **PostgreSQL 18 掛 `/var/lib/postgresql`**（tuning-log）：掛 `/data` 那層資料會寫在容器內，重建即遺失。

## 相依與版本

- **相依沒鎖版本**（log-analysis）：DuckDB 2.0 在兩次發版間推出，image 撿到新版、8 個測試失敗，本機全過。
  從第一天就用 `uv.lock`，Dockerfile `uv sync --locked`。
- **MES MongoDB 4.0 → pymongo 鎖 `>=4.13,<4.14`**（tuning-log）：4.14 起連不上 wire version 7，假實作測不出來。
  加測試檢查 `MIN_SUPPORTED_WIRE_VERSION <= 7`。
- **TypeScript 鎖 `~6.0`**（tuning-log）：typescript-eslint 8 的 peer 是 `<6.1.0`。
- **SDK 方法名照實際安裝版本寫**（log-analysis）：照文件或記憶寫會錯；寫 `inspect.signature` 的 smoke 檢查。
- **警告數**：舊 repo 以基線數當迴歸訊號、不 `filterwarnings` 掉；新 repo 直接 `-W error`。

## CUDA

- **執行時才編 kernel 的套件，nvcc 不能比 GPU 機的 driver 新**（timeseries-model-experiment）：TiRex-2 的 `flashrnn`
  只產生 PTX、靠 driver JIT；driver 550（CUDA 12.4）認不得 nvcc 12.6 的 PTX。devel base 要對齊 driver
  （`nvidia/cuda:12.4.1-devel`），torch wheel 可以較新（cu126，靠 minor version compatibility）。
- **根目錄是大型環境時，SessionStart hook 不要 sync 它**（timeseries-model-experiment）：含 torch 約 6 GB，
  每個雲端 session 都會重裝；把工具拆到 `tools/` 另一個 uv 專案，hook 只 sync 那個。
- **`--user` 的 uid 不在 `/etc/passwd`**（timeseries-model-experiment）：torch inductor 載入時呼叫 `getpass.getuser()` 會
  `KeyError`；image 設 `USER`，發版檢查一律以 `--user 1000:1000` 跑。
- **nvidia/cuda base 的 entrypoint 印 banner 到 stdout**（timeseries-model-experiment）：Dockerfile 設 `ENTRYPOINT []`。
- **雲端 dockerd 的 containerd image store 讓大 image 佔兩倍**（timeseries-model-experiment）：
  `/etc/docker/daemon.json` 設 `{"features":{"containerd-snapshotter":false}}` 再啟動。
- **`docker save` 先把整個 image 解到 daemon 暫存目錄**（timeseries-model-experiment）：匯出大 image 時要 image＋暫存＋gz 三份空間；
  ubuntu-24.04 runner 的 `/mnt` 與 `/` 同一顆磁碟，搬 `DOCKER_TMPDIR` 沒用，只能把 `/` 上的預裝工具清掉（swap、Swift、JVM、`.ghcup`、toolcache…）。
- **雲端拉 Docker Hub 會 429**（timeseries-model-experiment）：暫存副本改用 `mirror.gcr.io/<image>`，先比對 digest。

## 網路與內網

- **企業 SSL-decrypt CA**（log-analysis）：`update-ca-certificates` 不夠，httpx 走 certifi，要 `SSL_CERT_FILE` 指回系統 bundle。
  CA 不進版控，build 期放 `certs/`（只 commit `.gitkeep`），執行期掛載。
- **判斷 proxy 通不通要實際打一次**（log-analysis）：`ss -ltn` 看不到不代表不存在。
- **GitHub 網頁上傳傳不了 `.` 開頭資料夾**（tuning-log）：bundle 放 repo 根目錄；`.gitignore` 的 `*.bundle` 讓模擬時要 `git add -f`。
- **`import-bundle` 用 `GITHUB_TOKEN` 推不了改動 workflow 的 commit**（tuning-log）：本機不改 `.github/workflows/`。

## LLM

- **地端 vLLM（Qwen3、GLM）預設開 thinking**（log-analysis、sol-pi）：reasoning 吃光 `max_tokens`，`content` 是 `null`。
  帶 `chat_template_kwargs: {"enable_thinking": false}`，並用測試鎖住。
- **重問時要帶真正的失敗原因**（log-analysis）：從 `ValidationError.errors()` 取 `loc`＋`msg`，不用 `str(exc)`（會回音原始輸出）。
- **評估模型前先確認測試資料形狀是真的**（log-analysis）：假資料的形狀讓任務根本做不到，差點誤判模型能力。
- **不把整份資料送進 LLM**（log-analysis）：只送樣本與摘要。

## Windows

- **`.cmd`／`.ps1` 用 CRLF**（sol-pi）：`.gitattributes` 設 `*.ps1 text eol=crlf`、`*.cmd text eol=crlf`；`.cmd` 只用 ASCII。
