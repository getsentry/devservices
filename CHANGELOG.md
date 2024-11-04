## 0.0.5

### Various fixes & improvements

- fix(logs): Limit log length and check to ensure service is running before printing logs (#114) by @hubertdeng123
- fix(list-services): Use state for finding status of list services (#108) by @hubertdeng123
- ref(status): Improving status command when service isn't running (#113) by @IanWoodard
- include container name in status (#112) by @hubertdeng123
- chore(errors): Adding graceful handling when docker daemon isn't running (#99) by @IanWoodard
- feat(purge): adding purge command (#84) by @IanWoodard
- feat(devservices): Proper stop logic to account for shared remote services (#104) by @hubertdeng123
- feat(state): Add state with sqlite db (#103) by @hubertdeng123
- chore(errors): Improving the error msgs for dependency errors (#101) by @IanWoodard
- fix(logs): Fixing naming issue with logs (#102) by @IanWoodard
- fix for when services to use is empty (#93) by @hubertdeng123

## 0.0.4

### Various fixes & improvements

- feat(devservices): Run commands for nested dependencies by project (#86) by @hubertdeng123
- ref(dependencies): Providing information about installed remote dependencies after installing (#82) by @IanWoodard
- fix missing directory for docker user plugin (#81) by @hubertdeng123
- ref(dependencies): Adding ability to install nested dependencies (#77) by @IanWoodard
- feat(commands): Add update command (#75) by @hubertdeng123
- only run codecov on pull requests (93cfd424) by @hubertdeng123
- ref(services): Add message when service is found with invalid config (#73) by @IanWoodard
- ref: Pin docker compose version for users (#68) by @hubertdeng123
- chore(utils): Updating usage to use a constant (#74) by @IanWoodard
- ref(dependencies): Adding git proper git config management for deps (#69) by @IanWoodard
- feat(docker-compose): Simplify docker compose environment injection (#64) by @IanWoodard
- feat(list-services): Add status of services (#55) by @hubertdeng123
- feat(docker-compose): Check version (#53) by @hubertdeng123
- chore(sentry): Add option to disable sentry (#59) by @IanWoodard
- feat(dependency): Adding dependency management to commands (#56) by @IanWoodard
- Ignoring testing and tests for coverage (#57) by @IanWoodard
- add venv (#54) by @hubertdeng123
- feat(codecov): Adding codecov (#50) by @IanWoodard
- chore(pre-commit): Add a few pre commit plugins (#51) by @hubertdeng123
- chore(sentry): Add sentry environment support (#49) by @IanWoodard
- ref(dep): Addressing dependency edge cases (#44) by @IanWoodard
- ref(docker-compose): refactoring docker compose util (#48) by @IanWoodard
- chore(start): Specify project name when starting services (#47) by @hubertdeng123
- add installation details (#42) by @hubertdeng123

_Plus 3 more_

## 0.0.3

### Various fixes & improvements

- feat(release): Build and upload binary (#36) by @hubertdeng123
- clean up help menu (#35) by @hubertdeng123
- feat(config): Rename docker-compose.yml file to config.yml (#38) by @hubertdeng123
- ref(service-config): Updating service config to include remote deps (#37) by @IanWoodard
- feat(status): Add url (#34) by @hubertdeng123
- dynamically get installed version (#33) by @hubertdeng123
- add readme (#32) by @hubertdeng123

## 0.0.2

### Various fixes & improvements

- restructure modules for packaging (#31) by @hubertdeng123
- feat(python): Support python 3.10 (#30) by @hubertdeng123

## 0.0.1

- No documented changes.
