# devservices

`devservices` is a CLI that brings a service's development dependencies up and down. It reads them from the `devservices/config.yml` file in your repository.

## Requirements

- Docker must be running. If Docker Compose is missing or older than 2.29.7, `devservices` downloads a newer Compose into your Docker CLI plugins directory.
- Commands that take a service name, and `devservices list-services`, look for repositories in the devenv `coderoot` set in `~/.config/sentry-devenv/config.ini`.

## Install

1. Add `devservices` to your repository's `requirements.txt` and install it in your virtualenv:

   ```
   devservices==1.2.4
   ```

2. Add a `devservices/config.yml` file to your repository. See [Configuration](#configuration).
3. Run `devservices up`.

## Commands

If you omit `<service-name>`, `devservices` uses the `devservices/config.yml` file in the current directory. Run `devservices <command> --help` for every flag.

- `devservices up <service-name>`: Bring up a service and its dependencies. Use `--mode <mode>` to pick a mode other than `default`. Use `--offline` to use cached dependencies and images.
- `devservices down <service-name>`: Bring down a service and its dependencies.
- `devservices status <service-name>`: Show the status and ports of a running service and its dependencies.
- `devservices logs <service-name>`: Show logs for a running service.
- `devservices list-services` (alias `ls`): List running services. Use `--all` to include stopped services in your coderoot.
- `devservices list-dependencies <service-name>`: List a service's dependencies.
- `devservices toggle <service-name> [local|containerized]`: Switch a service's runtime between containerized and local.
- `devservices serve`: Run the `devserver` program from the current directory's `x-programs` block. Arguments after `serve` go to the devserver.
- `devservices foreground <program-name>`: Stop a background program and run it in the foreground for interactive debugging.
- `devservices reset <service-name>`: Remove the volumes of a Docker Compose service.
- `devservices purge <service-name>`: Remove all devservices state, cached dependencies, containers, and volumes. If you pass a service name, `purge` asks for confirmation and removes only that service.
- `devservices update`: Update devservices to the latest version.

The global `-c <path>` flag (`--config`) loads a config file from another path. You cannot combine `-c` with a service name.

## Environment variables

- `GITHUB_TOKEN` or `GH_TOKEN`: Token for downloading remote dependencies from GitHub. Without one, `devservices` uses `gh auth token`, then falls back to rate-limited unauthenticated downloads.
- `DEVSERVICES_DISABLE_SENTRY=1`: Stop sending errors and traces to Sentry.

## Configuration

`devservices/config.yml` is a Docker Compose file with an `x-sentry-service-config` block and an optional `x-programs` block. Other files in the `devservices` directory are optional. You usually use them for volume mounts.

```yaml
# devservices settings:
# - version: Config file version. The only valid value is 0.1.
# - service_name: The name you pass to commands such as `devservices up <service-name>`.
# - dependencies: Each dependency accepts only `description` and `remote`.
#   - A dependency without `remote` must match a service in `services` or a program in `x-programs`.
#   - A dependency with `remote` is fetched from the `devservices` directory of that repository. Example: https://github.com/getsentry/snuba/blob/59a5258ccbb502827ebc1d3b1bf80c607a3301bf/devservices/config.yml#L8
# - modes: Each mode lists the dependencies it runs. A `default` mode is required.
# - healthcheck_timeout: Optional. Seconds to wait for all containers to become healthy. Defaults to 180.
x-sentry-service-config:
  version: 0.1
  service_name: example-service
  dependencies:
    example-dependency-1:
      description: Example dependency defined in the config file
    example-dependency-2:
      description: Example dependency defined in the config file
    example-remote-dependency:
      description: Remote dependency defined in the `devservices` directory in the example-repository repo
      remote:
        repo_name: example-repository
        branch: main
        repo_link: https://github.com/getsentry/example-repository.git
        mode: default # Optional. The remote dependency's mode. Defaults to `default`.
  modes:
    default: [example-dependency-1, example-remote-dependency]
    custom-mode: [example-dependency-1, example-dependency-2, example-remote-dependency]

# Programs that devservices runs with supervisor. List a program in `dependencies` to start and stop it with `devservices up` and `devservices down`.
# - `devservices foreground <program-name>` runs a program in the foreground.
# - `devservices serve` runs the program named `devserver`.
x-programs:
  devserver:
    # Required.
    command: "python manage.py run_server"
    # Optional: any supervisor program setting from https://supervisord.org/configuration.html#program-x-section-settings

  example-worker:
    command: "python manage.py worker"

# Standard Docker Compose services: https://docs.docker.com/reference/compose-file/services/
# - Publish ports on 127.0.0.1 only.
# - Put every service on the `devservices` network.
# - Add the `orchestrator=devservices` label. `devservices purge` and `devservices reset` find containers by this label.
# - Add a healthcheck. `devservices up` waits for containers to become healthy.
# - Use `volumes` to keep data between runs or to bind mount local files. Example: https://github.com/getsentry/snuba/blob/59a5258ccbb502827ebc1d3b1bf80c607a3301bf/devservices/config.yml#L44
services:
  example-dependency-1:
    image: ghcr.io/getsentry/example-dependency-1:1.0.0
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    healthcheck:
      test: wget -q -O - http://localhost:1234/health
      interval: 5s
      timeout: 5s
      retries: 3
    environment:
      EXAMPLE_ENV_VAR: example-value
    volumes:
      - example-dependency-1-data:/var/lib/example-dependency-1
    restart: unless-stopped
    # devservices requires the fields below.
    ports:
      - 127.0.0.1:1234:1234
    extra_hosts:
      host.docker.internal: host-gateway
    networks:
      - devservices
    labels:
      - orchestrator=devservices

  example-dependency-2:
    image: ghcr.io/getsentry/example-dependency-2:1.0.0
    command: ["devserver"]
    healthcheck:
      test: curl -f http://localhost:2345/health
      interval: 5s
      timeout: 5s
      retries: 3
    environment:
      EXAMPLE_ENV_VAR: example-value
    restart: unless-stopped
    # devservices requires the fields below.
    ports:
      - 127.0.0.1:2345:2345
    extra_hosts:
      host.docker.internal: host-gateway
    networks:
      - devservices
    labels:
      - orchestrator=devservices

# Standard Docker Compose volumes: https://docs.docker.com/reference/compose-file/volumes/
volumes:
  example-dependency-1-data:

# The external `devservices` network is required. `devservices up` creates it if it does not exist.
# Docker Compose networks reference: https://docs.docker.com/reference/compose-file/networks/
networks:
  devservices:
    name: devservices
    external: true
```

## Get help

Open an issue in [getsentry/devservices](https://github.com/getsentry/devservices/issues).

## License

See [LICENSE.md](LICENSE.md).
