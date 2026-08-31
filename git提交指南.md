**第一步：获取代码并切换到你的专属分支**

* 首先克隆整个团队的代码仓库到你的电脑上：
`git clone [https://github.com/system0618/Smart-Mattress-Project.git](https://github.com/system0618/Smart-Mattress-Project.git)`
* 进入项目文件夹：
`cd Smart-Mattress-Project`
* 切换到属于你的开发分支（例如孙瑜泽的弱力区域增强分支）：
`git switch feature/pressure-enhancement`
*(注意：如果本地还没有这个分支，第一次创建并切换请使用 `git switch -c feature/你的分支名`)*

**第二步：写代码与保存到本地 (Commit)**

* 当你在本地写完一段完整的代码、跑通了一个小功能或修复了 Bug 后，请立刻保存。尽量避免积攒好几天才提交一次，细粒度的提交对 git log 考核更有利。


* 查看修改了哪些文件（红色的文件代表被修改或新建）：
`git status`
* 将所有修改添加到暂存区：
`git add .`
* 提交并附带说明（用一句话清晰说明完成了什么）：
`git commit -m "feat: 完成弱压力区域的灰度图转换逻辑"`
*(建议采用标准动作前缀：`feat:` 代表新功能，`fix:` 代表修 Bug，`docs:` 代表改文档)*

**第三步：推送到 GitHub 远程仓库 (Push)**

* 把本地保存好的记录同步到 GitHub 的云端分支上：
`git push`
* *(注意：如果是第一次在本地新建分支并推送，系统会提示运行类似 `git push --set-upstream origin 你的分支名` 的命令，直接复制该命令运行即可)*

**第四步：发起合并请求 (Pull Request)**

* 当你的模块开发完毕，需要将代码合并到主干 `main` 分支时，请在 GitHub 网页端完成操作。
* 打开 GitHub 仓库网页，页面顶部会出现一个黄色的提示条，显示你刚刚推送了分支，点击旁边的 **Compare & pull request** 绿色按钮。
* 检查合并方向：确保是 `base: main` <--- `compare: feature/你的分支`。
* 填写简短的修改说明，点击 **Create pull request**。
* 在团队群内提醒其他队友进行代码审查（Code Review），确认无误后由他人点击 Merge 完成合并。

**AI 协同开发记录提交规范**

* 课程强制要求每人必须提交一份与 AI 的完整会话记录（markdown 或 json 格式）。


* 开发过程中，请务必将你的工具对话记录保存到仓库的 `ai_logs/` 文件夹下，并按照上述 `add -> commit -> push` 流程推送到远程仓库。