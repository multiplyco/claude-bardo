# QA suite

Five sessions, each started with its own flags and asked to reply with one word:

| session | extra | dies by | stands for | expected after restore |
|---|---|---|---|---|
| alpha | | SIGHUP | terminal crash | back, remembers its word |
| bravo | wrapped in `caffeinate -i --` | SIGTERM | reboot | back, still under caffeinate |
| charlie | | SIGKILL | power loss | back |
| delta | `--allow-dangerously-skip-permissions` | SIGTERM | reboot | back, **without** the bypass flag |
| echo | | `/exit` | deliberate exit | stays closed |

Every session runs `claude --setting-sources project,local --settings <qa hooks> --model haiku
--permission-mode default --session-id <fresh uuid> "<prompt>"`.

| id | name | covers | steps | expected |
|---|---|---|---|---|
| TC-00 | sanity gate | the environment, not the tool | `claude --version`, `claude auth status`, `claude-bardo --version`, drive the terminal once | all succeed; otherwise every case is NOT_RUN |
| TC-01 | launch | sessions start and answer | open five windows, answer the trust prompt if shown, wait for a reply in each transcript | five replies (INCONCLUSIVE on timeout) |
| TC-02 | hook records | the SessionStart hook | read the run's registry | five start records with pid and exact argv, `--model` kept, bravo's caffeinate seen, the prompt text nowhere on disk |
| TC-03 | live | the fold, while running | `list --json` | all five `live` |
| TC-04 | four deaths | what Claude Code leaves behind | send the signals, type `/exit`, wait for the processes to exit | SessionEnd `other` for alpha, bravo, delta; none for charlie; `prompt_input_exit` for echo |
| TC-05 | classified | the fold, after death | `list --all --json` | alpha, bravo, delta `interrupted`; charlie `killed`; echo `closed`; delta's bypass flag reported |
| TC-06 | restore | restore by id | `restore <4 ids>`; `restore <echo>` | rc 0 and four windows; echo refused with rc 1 |
| TC-07 | relaunched | the replay policy, live | find each `claude … --resume <id>` process | four processes carrying `--model`, `--settings`, `--setting-sources`, `--permission-mode`; none carrying the bypass flag; bravo under caffeinate; no process for echo |
| TC-08 | live again | restored sessions re-register | `list --json` | the four `live`, echo still `closed` |
| TC-09 | memory | the conversation survived | ask alpha, in its restored window, which word it replied with | a new reply containing alpha's word |
| TC-10 | no doubles | restore is safe to repeat | `restore <alpha> --dry-run` while alpha is live | rc 1: nothing to restore |
| TC-11 | fork | the rehearsal mode | `restore --fork <alpha>` while alpha is live | a `claude … --resume <alpha> --fork-session` process; a new session id registered without `--fork-session` in its argv; alpha still live |
