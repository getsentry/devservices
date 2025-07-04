## 1.2.1

### Various fixes & improvements

- chore(config): Consolidate programs.conf file into config.yml (#285) by @hubertdeng123
- feat(up/down): Multithread bringing up/down supervisor programs (#286) by @hubertdeng123
- chore(readme): Add serve (#288) by @hubertdeng123
- add foreground command to readme (#287) by @hubertdeng123

## 1.2.0

### Various fixes & improvements

- feat(logs): Support supervisor programs (#283) by @hubertdeng123
- feat(status): `devservices status` now supports supervisor processes (#282) by @hubertdeng123
- fix(up): `devservices up` will not restart supervisor if it is already running (#284) by @hubertdeng123
- feat(foreground): Add foreground command (#281) by @hubertdeng123
- feat(down): Add supervisor programs to down (#278) by @hubertdeng123
- feat(up): Add capability of starting supervisor processes to up (#276) by @hubertdeng123
- ref(up): Adding more context to up (#279) by @IanWoodard
- fix(up): Fixing local runtime dependency mode (#280) by @IanWoodard
- feat(config): Add supervisor programs dependency validation (#275) by @hubertdeng123
- feat(config): Add validation for non remote dependencies (#274) by @hubertdeng123

## 1.1.6

### Various fixes & improvements

- chore: Make `devservices` forward compatible with Python SDK 3.0.0 (#277) by @antonpirker
- feat: exponentially retry pulling (#266) by @joshuarli

## 1.1.5

### Various fixes & improvements

- feat(toggle): Updating toggling active dependency to be consistent (#273) by @IanWoodard
- fix(up/down): Fixing the exclude-local flag for up/down (#272) by @IanWoodard
- fix(up): Cleaning up 'up' local runtime logic (#271) by @IanWoodard
- feat(reset): Adding reset command (#219) by @IanWoodard

## 1.1.4

### Various fixes & improvements

- Revert "add devenv and frozen requirements (#255)" (#270) by @hubertdeng123

## 1.1.3

### Various fixes & improvements

- add supervisor to pyproject toml (#269) by @hubertdeng123

## 1.1.2

### Various fixes & improvements

- add devenv and frozen requirements (#255) by @joshuarli
- chore(versioning): Bumping min python version to 3.11 (#268) by @hubertdeng123
- ref(toggle): Auto bring up/down local runtimes services (#267) by @IanWoodard
- change terminology of program vs process (#262) by @hubertdeng123
- fix(toggle): Fixing toggle enums again (#265) by @IanWoodard
- feat(serve): Add initial serve command (#258) by @hubertdeng123
- fix(toggle): Fixing toggle formatting with enums (#264) by @IanWoodard

## 1.1.1

### Various fixes & improvements

- feat: vendor docker-compose binaries (#263) by @joshuarli
- feat(supervisor): Add tailing logs function (#257) by @hubertdeng123
- chore(toggle): Add documentation for toggle (#261) by @IanWoodard
- chore(supervisor): Add some socket tests (#259) by @hubertdeng123

## 1.1.0

### Various fixes & improvements

- feat(toggle): add toggle command (#256) by @IanWoodard
- feat(supervisor): Generate supervisor config file to local dir (#252) by @hubertdeng123
- fix(up): Only show skipped message once (#254) by @IanWoodard
- fix(status): Fixing status indentation (#253) by @IanWoodard
- ref(status): Revamp status command (#251) by @IanWoodard
- feat(supervisor): Add initial supervisor logic (#250) by @hubertdeng123
- ref(up): Add info about local runtime in up (#249) by @IanWoodard
- fix healthcheck bug (#247) by @hubertdeng123
- ref(dependency-graph): Adding more context to the dependency graph (#248) by @IanWoodard

## 1.0.18

### Various fixes & improvements

- feat(up): Add text verbosity for healthchecks (#245) by @hubertdeng123
- ref(down): Updating down to work with local runtime (#243) by @IanWoodard
- feat(up): Add better UX when pulling images (#242) by @hubertdeng123
- fix(tests): Fixing test variable naming (#244) by @IanWoodard
- feat(runtime): Updating up to handle local runtime (#240) by @IanWoodard
- feat(ci): Add tags for ci runs (#241) by @hubertdeng123
- feat(runtime): Adding state to track runtime (#238) by @IanWoodard
- fix(gha): Updating actions/cache to 4.2.0 (#239) by @IanWoodard
- feat(readme): Add config section to readme (#234) by @hubertdeng123

## 1.0.17

### Various fixes & improvements

- feat(sentry): Manually set status of transactions (#237) by @hubertdeng123

## 1.0.16

### Various fixes & improvements

- chore(docker-compose): Move `docker compose version` command to separate function (#232) by @hubertdeng123
- fix(docker-compose): Smarter detection of docker config dir (#231) by @hubertdeng123
- chore(sentry): updating platform tag name (#230) by @IanWoodard
- chore(sentry): Fixing status for down when not running (#229) by @IanWoodard

## 1.0.15

### Various fixes & improvements

- bump the sentry sdk version (#228) by @hubertdeng123
- fix(dependencies): Only get dependencies that should be running based on modes (#226) by @IanWoodard
- chore(devservices): Fixing capitalization in update help message (#227) by @IanWoodard

## 1.0.14

### Various fixes & improvements

- ref(sentry): Tweak devservices environment env variable (#224) by @hubertdeng123
- fix(docker-compose): Allow docker compose verification logic to properly throw (#225) by @hubertdeng123
- fix(sentry): Fixing disable sentry env var logic (#223) by @IanWoodard
- ref(sentry): adding more context to sentry (#222) by @IanWoodard
- fix(dependencies): Exclude submodules from fetch (#221) by @IanWoodard

## 1.0.13

### Various fixes & improvements

- chore(healthchecks): Bump healthcheck timeout to 2 minutes (#220) by @hubertdeng123

## 1.0.12

### Various fixes & improvements

- chore(sentry): Adding sentry release (#218) by @IanWoodard

## 1.0.11

### Various fixes & improvements

- make env variable more clear (#217) by @hubertdeng123

## 1.0.10

### Various fixes & improvements

- ref(dependencies): Improving error messages for dependency errors (#216) by @IanWoodard
- ref(dependencies): Improving error handling for dependency logic (#215) by @IanWoodard
- ref(up): Show available modes (#214) by @IanWoodard
- chore(down): Cleaning up down tests (#213) by @IanWoodard
- ref(commands): Improving commands to use starting services and started (#212) by @IanWoodard
- fix(down): Enable bringing down starting services (#211) by @IanWoodard
- chore(state): Refactor state to support starting services table (#207) by @hubertdeng123
- ref(dependencies): Switching to debug logs and sentry messages (#209) by @IanWoodard
- fix(logger): Update logger to no longer use fstrings (#206) by @IanWoodard
- use more specific error message for docker compose error exception (#208) by @hubertdeng123
- chore(up): Cleaning up tests (#205) by @IanWoodard

## 1.0.9

### Various fixes & improvements

- chore: Moving get_docker_compose_commands_to_run back (#204) by @IanWoodard
- chore(ci): Skip loader for CI (#203) by @hubertdeng123
- fix(dependencies): Adding retries to fetch (#202) by @IanWoodard
- fix(down): Fixing down's logic and adding proper tests (#201) by @IanWoodard
- fix(up): Cleaning up 'up' test cases (#199) by @IanWoodard
- ref(docker-compose): Starting to refactor docker compose logic (#198) by @IanWoodard
- chore(up): cleaning up tests (#196) by @IanWoodard
- ref(commands): Improving error message for service not found DEVINFRA-572 (#197) by @IanWoodard
- ref(commands): Improving error messages (#195) by @IanWoodard
- fix(down): Use stop rather than down to avoid removing containers (#194) by @IanWoodard

## 1.0.8

### Various fixes & improvements

- fix(status): Adding consistent ordering to status output (#191) by @IanWoodard
- add missing depenedencies (#193) by @hubertdeng123
- remove update warning message (#189) by @hubertdeng123
- chore: cleaning up various nits (#192) by @IanWoodard
- chore: Bump healthcheck timeout to 45 seconds (#190) by @hubertdeng123

## 1.0.7

### Various fixes & improvements

- fix(purge): Updating purge to stop/remove all devservices containers (#188) by @IanWoodard
- feat(devservices): Add healthcheck wait condition and parallelize starting of containers (#178) by @hubertdeng123
- ref(purge): Cleaning up purge network logic (#186) by @IanWoodard
- fix(up): Always pull new images (#187) by @IanWoodard
- chore(docker): Cleaning up docker utils (#185) by @IanWoodard
- feat(purge): Purge removes corresponding volumes (#184) by @IanWoodard
- feat(devservices): Return namedtuple for docker compose command (#183) by @hubertdeng123
- ref(dependencies): Adding more context to sentry (#181) by @IanWoodard

## 1.0.6

### Various fixes & improvements

- fix(down): Adding error handling to get_non_shared_remote_dependencies (#180) by @IanWoodard
- ref(update): Adding caching to checking for latest version (#179) by @IanWoodard
- avoid checking for update in CI (#177) by @hubertdeng123
- feat(purge): Updating purge to only stop relevant containers (#176) by @IanWoodard

## 1.0.5

### Various fixes & improvements

- fix(dependencies): Only install dependenices needed for the mode (#175) by @IanWoodard
- use expanduser (#174) by @hubertdeng123
- ref(modes): Refactoring modes to support multiple concurrent modes (#173) by @IanWoodard
- fix(dependencies): Fixing dependency graph construction for simple modes (#172) by @IanWoodard
- ls should show mode of service that is running (#170) by @hubertdeng123
- Replace release bot with GH app (#171) by @Jeffreyhung
- fix(sentry): Do not report to sentry if service is not found (#169) by @hubertdeng123
- test list dependencies (#168) by @hubertdeng123
- feat(services): Adding find_matching_service test (#167) by @IanWoodard
- feat(services): Adding test for skipping non-devservices repos (#166) by @IanWoodard
- feat(tests): Test status command (#165) by @hubertdeng123
- feat(services): Adding test for local services with invalid config (#164) by @IanWoodard

## 1.0.4

### Various fixes & improvements

- feat(dependency): Adding dependency graph to start services (#163) by @IanWoodard
- fix(up): Restart services when switching modes (#160) by @IanWoodard
- remove capture output flag (#162) by @hubertdeng123
- feat(network): Create devservices network if it doesn't exist (#161) by @hubertdeng123
- feat(devservices): Start shared services first (#159) by @hubertdeng123

## 1.0.3

### Various fixes & improvements

- feat(devservices): Remove healthcheck and multithreading for beta (#158) by @hubertdeng123
- fix(commands): Cleaning up unused args (#157) by @IanWoodard
- ref(commands): Cleaning up exception handling (#156) by @IanWoodard
- feat(devservices): Support modes for up/down (#152) by @hubertdeng123
- fix(purge): Fixing purge test (#155) by @IanWoodard
- feat(testing): Add tests for `install_and_verify_dependencies` for modes (#153) by @hubertdeng123
- fix(status): Fixing doc-string (#154) by @IanWoodard
- ref(dependencies): Updating dependency management to handle modes (#151) by @IanWoodard
- feat(stop): Add more context for what is going on underneath the hood for stop (#149) by @hubertdeng123
- feat(start): Add more context to what is going on underneath the hood for start (#148) by @hubertdeng123
- ref(purge): removing docker networks with purge (#150) by @IanWoodard
- ref(start/stop): Renaming start and stop to up and down (#147) by @IanWoodard
- ref(docker-compose): De-abstracting run_docker_compose_command (#146) by @IanWoodard
- feat(start): Add threading and condition to wait for containers to be healthy (#144) by @hubertdeng123
- add cwd for debug logs for dependencies (#141) by @hubertdeng123
- feat(sentry): Adding version tag, cleaning up version logic (#145) by @IanWoodard
- feat(sentry): Adding user to sentry (#139) by @IanWoodard
- feat(sentry): Adding explicit capture for exceptions (#138) by @IanWoodard

## 1.0.2

### Various fixes & improvements

- fix(logs): Fixing bug in logs command, adding tests (#137) by @IanWoodard

## 1.0.1

### Various fixes & improvements

- fix(debug): Fixing debug flag (#135) by @IanWoodard

## 1.0.0

### Various fixes & improvements

- feat(readme): Update installation instructions (#134) by @hubertdeng123
- fix(dependencies): Removing sparse-checkout clear command (#133) by @IanWoodard
- feat(purge): Adding state clear functionality to purge (#125) by @IanWoodard
- feat(debug): Add debug mode for start and stop (#131) by @hubertdeng123
- ref(docker-compose): Moving dependency logic out of docker compose (#129) by @IanWoodard
- fix(logs): Fixing None case (#130) by @IanWoodard
- ref(logs): Updating logs to use console util (#117) by @IanWoodard
- chore(readme): Add update and purge to README (#115) by @hubertdeng123

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
