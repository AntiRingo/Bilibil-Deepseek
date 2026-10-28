# 服务器部署与更新

适用：Ubuntu 24.04 LTS / Debian 系、systemd、单个 B站账号。建议 4核4GB 或 2核4GB。
当前仓库根目录包含 `bilibili-ai-bot/`，不是直接以 Python 文件所在目录作为 Git 根目录。
本方案默认通过 SSH 隧道管理，不需要域名，也不要开放公网 5000 端口。

## 目录与数据保留

| 路径 | 用途 |
| --- | --- |
| `/opt/bilibili-bot/repo` | Git 源码仓库，仅用于拉取和选定版本 |
| `/opt/bilibili-bot/releases/<版本>-<随机后缀>` | 每次部署独立代码、虚拟环境和依赖版本记录 |
| `/opt/bilibili-bot/current` | 当前运行版本的符号链接 |
| `/var/lib/bilibili-bot/config.json` | 服务器自己的配置、Cookie、API Key |
| `/var/lib/bilibili-bot/data/` | 记忆、聊天记录、图片、去重记录等 |
| `/etc/bilibili-bot/environment` | 固定会话密钥、时区和运行环境设置 |
| `/opt/bilibili-bot/backups/` | 更新前的配置与数据备份（包含敏感信息） |

代码发布只使用 `git archive` 导出指定提交，不复制本地未提交文件，不覆盖服务器配置和数据。
`BILI_STATE_DIR` 使程序把工作目录切换到独立数据目录；未设置时兼容原来的本地启动方式。
配置新增字段由默认值补齐，不自动覆盖已有值。修改数据结构的未来更新仍需另写并测试迁移。

## 1. 首次部署

先确认准备部署的提交已推送到你自己的 Git 远程仓库。私有仓库建议使用只读部署密钥；不要在 URL 中放 Token。
以下命令在服务器运行。`仓库地址` 和 `已发布提交SHA` 必须替换为真实值。

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg curl ca-certificates
sudo install -d -m 755 /opt/bilibili-bot
sudo git clone 仓库地址 /opt/bilibili-bot/repo
cd /opt/bilibili-bot/repo
sudo bash deploy/deploy.sh /opt/bilibili-bot/repo 已发布提交SHA
```

脚本为服务创建无登录权限的 `bilibili-bot` 用户，安装独立 Python 环境，运行隔离测试，生成随机面板密码和会话密钥，配置并启动管理面板。
首次安装不会启动机器人，也不会替你向 B站发消息。安装依赖需要服务器能访问 PyPI。
依赖每次安装的确切版本记录在各版本目录的 `installed-requirements.txt`；回退使用旧虚拟环境。
当前上游依赖未全部锁定，新部署可能解析出更新依赖，需通过离线测试和上线验证后使用。

在你自己的 Windows PowerShell 中建立隧道（保持窗口开启；如 SSH 不是22端口，加 `-p 端口`）：

```powershell
ssh -L 15000:127.0.0.1:5000 用户名@服务器IP
```

浏览器打开 `http://127.0.0.1:15000`。初始密码仅在服务器自己的终端查看，不发送到聊天：

```bash
sudo python3 -c 'import json; print(json.load(open("/var/lib/bilibili-bot/config.json"))["CHAT_PASSWORD"])'
```

在面板填写模型 URL、Key、模型名，测试连接，扫码登录 B站，设置主人 UID 和功能开关。
Embedding Key 可不填，此时不执行语义向量检索。生产密码至少12位。
确认需要真实回复后，再启用机器人：

```bash
sudo systemctl enable --now bilibili-bot
sudo systemctl status bilibili-web bilibili-bot
sudo journalctl -u bilibili-bot -n 80 --no-pager
```

`active` 只代表进程在运行；需要另行验证模型可达、Cookie 有效、新消息处理正常。
不要让本地和服务器同时运行同一 B站账号的机器人。

## 2. 迁移本地配置和记忆（可选）

先停止本地机器人，备份本地 `config.json` 和整个 `data/`。在服务器停止两个服务后，通过 SCP/SFTP 将它们放到 `/var/lib/bilibili-bot/`。
这是首次迁移时由你明确选择的操作，日常更新不要再次上传它们。

```bash
sudo systemctl stop bilibili-bot bilibili-web
# 在此通过 SCP/SFTP 迁入 config.json 和 data/（先备份目标文件）
sudo chown -R bilibili-bot:bilibili-bot /var/lib/bilibili-bot
sudo chmod -R go-rwx /var/lib/bilibili-bot
sudo systemctl start bilibili-web
```

若迁来的配置存有 `CHAT_PASSWORD`，它必须至少12位且不是默认密码，否则面板会拒绝启动；未设置密码时，应先在服务器本地配置强密码。
检查配置、历史记录、图片和去重状态后再启动机器人。不要上传 `.venv`、缓存和临时视频。

## 3. 后续发布

本地修改 → 离线测试 → Git 提交 → 推送 → 服务器拉取并部署指定提交。
不要在服务器当前版本目录里修改代码；紧急修复也应回到源码仓库形成提交。

本地：

```powershell
cd bilibili-ai-bot
python -m unittest discover -s tests -p "test_*.py"
cd ..
git status
git add 需要发布的代码路径
git commit -m "描述本次功能更新"
git push origin 当前开发分支
git rev-parse HEAD
```

服务器（替换 SHA）：

```bash
sudo git -C /opt/bilibili-bot/repo fetch --prune origin
sudo bash /opt/bilibili-bot/current/deploy/deploy.sh /opt/bilibili-bot/repo 新提交SHA
```

脚本先安装并测试新版本，再短暂停止两个服务及子进程，备份状态，切换版本并检查面板健康接口。
如果机器人更新前正在运行，则重新启动；原来停止的机器人保持停止。
切换阶段失败会尝试恢复旧代码与服务；不要因看到失败就反复启动，先查看日志。
部署脚本自身有重大变化时，应按该版本说明，先在源码仓库检出并检查新脚本，再执行新脚本。

## 4. 回退和备份

```bash
sudo bash /opt/bilibili-bot/current/deploy/rollback.sh
```

回退到上一次发布的代码及依赖，保留最新配置和数据。回退前也会备份数据；如果旧版无法读取新版数据，应停止服务并人工执行对应迁移/恢复。
若回退后面板检查失败，脚本会尝试切回回退前的代码和服务状态，需要查看日志确认恢复结果。
自动备份只在发布/回退时进行，不能代替日常备份。建议定期停服务后备份 `/var/lib/bilibili-bot` 与 `/etc/bilibili-bot`，加密保存到另一台设备。
备份和旧版本不会自动删除，避免误删唯一恢复点；需要定期检查磁盘空间并保留最近几个已验证版本。

## 5. 日志、停止与公网访问

```bash
sudo journalctl -u bilibili-web -u bilibili-bot -f
sudo systemctl stop bilibili-bot
sudo systemctl restart bilibili-web
sudo cat /opt/bilibili-bot/current/REVISION
```

服务进程只监听 `127.0.0.1:5000`。若需要通过域名访问，先配置 Nginx 和 HTTPS，参考 `deploy/nginx.conf.example`，再设置 `/etc/bilibili-bot/environment` 中的 `COOKIE_SECURE=1` 并重启面板。
纯 SSH 隧道访问使用 `COOKIE_SECURE=0`。不要直接把5000端口开放公网；当前方案也没有提供公网登录限速，建议继续使用隧道。
使用单 Gunicorn worker/线程；当前多个后台进程共享 JSON 文件，还不是多账号/多实例高并发架构。

## 6. 正式部署前需要提供的信息

- 云厂商与服务器地域，系统名称及版本，是否已装宝塔/Docker或运行其他项目。
- 公网 IP、SSH 端口、登录用户名，账号是否有 sudo 权限。
- 登录方式：密钥或密码。只说明方式；不要在聊天里粘贴密码、私钥、API Key 或 Cookie。
- Git 仓库是否公开，使用当前 GitHub 仓库还是其他仓库，以及准备发布的分支。
- 是否迁移本地已有的配置和 `data/`，还是从空白配置开始。
- 只自己通过隧道访问，还是已有域名、需要 HTTPS 访问。

本地验证不能替代服务器上的 systemd、网络与账号功能验收。首次真实部署后须确认服务重启、模型连接、B站登录与消息收发。
