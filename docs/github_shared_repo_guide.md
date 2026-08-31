# GitHub 共享仓库操作说明

以下步骤需要仓库负责人在 GitHub 网页或已登录的 Git 命令行中完成。本地仓库骨架已经准备好，路径为：

```powershell
E:\workplace\Smart-Mattress-Project
```

## 1. 在 GitHub 创建远程仓库

1. 登录 GitHub。
2. 点击右上角 `+`，选择 `New repository`。
3. Repository name 填写 `Smart-Mattress-Project`。
4. Visibility 根据课程和团队要求选择 `Private` 或 `Public`。
5. 不要勾选自动创建 README、`.gitignore` 或 license，因为本地已经有这些文件。
6. 点击 `Create repository`。

## 2. 关联并推送本地仓库

在 PowerShell 中执行：

```powershell
cd E:\workplace\Smart-Mattress-Project
git remote add origin https://github.com/<你的用户名或组织名>/Smart-Mattress-Project.git
git branch -M main
git push -u origin main
```

如果提示 `remote origin already exists`，改用：

```powershell
git remote set-url origin https://github.com/<你的用户名或组织名>/Smart-Mattress-Project.git
git push -u origin main
```

如果 GitHub 要求登录，按终端提示完成浏览器授权或输入 Personal Access Token。

## 3. 邀请团队成员

1. 打开 GitHub 仓库页面。
2. 进入 `Settings` -> `Collaborators and teams`。
3. 点击 `Add people`。
4. 输入成员 GitHub 用户名并发送邀请。
5. 让成员在 GitHub 通知或邮箱中接受邀请。

## 4. 打开项目管理功能

课程要求使用平台项目管理功能，建议至少开启：

- `Issues`：记录任务、缺陷和文档工作。
- `Projects`：建立看板，例如 `Todo`、`In Progress`、`Review`、`Done`。
- `Pull requests`：每个功能分支通过 PR 合并。

建议初始 Issue：

- 睡姿识别 SVM 或 Random Forest 基线
- 睡姿识别 CNN 模型
- 身体部位划分数据标注与模型
- 弱压力区域增强算法
- Web 或 Unity 实时可视化
- API 数据接口联调
- AI 会话记录整理
- 个人报告模板整理

## 5. 成员日常开发命令

首次获取仓库：

```powershell
git clone https://github.com/<你的用户名或组织名>/Smart-Mattress-Project.git
cd Smart-Mattress-Project
```

开发新任务：

```powershell
git checkout -b feature/<成员名或任务名>
git add .
git commit -m "描述本次完成的工作"
git push -u origin feature/<成员名或任务名>
```

然后在 GitHub 页面创建 Pull Request。

## 6. 课程提交前导出 git log

在仓库根目录执行：

```powershell
git log --oneline --decorate --graph --all > docs/project_management/git_log.txt
git add docs/project_management/git_log.txt
git commit -m "Add team git log for submission"
git push
```

## 7. 需要人工确认的事项

- 仓库可见性：`Private` 还是 `Public`。
- 最终成员名单和 GitHub 用户名。
- 暂定结构中身体部位划分负责人为“姚乐”，AI 记录文件中包含“唐俊松”，请确认是否需要新增或重命名记录文件。
- 可视化技术路线：Web 前端还是 Unity，或两者都保留。
- 是否需要在 GitHub 开启分支保护，例如禁止直接推送到 `main`。
