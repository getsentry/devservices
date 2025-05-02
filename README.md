# devservices

A standalone cli tool used to manage dependencies for services. It simplifies the process of managing services for development purposes and bringing services up/down.

## Overview

`devservices` reads configuration files located in the `devservices` directory of your repository. These configurations define services, their dependencies, and various modes of operation.

## Usage

devservices provides several commands to manage your services:

### Commands

NOTE: service-name is an optional parameter. If not provided, devservices will attempt to automatically find a devservices configuration in the current directory in order to proceed.

- `devservices up <service-name>`: Bring up a service and its dependencies.
- `devservices down <service-name>`: Bring down service including its dependencies.
- `devservices status <service-name>`: Display the current status of all services, including their dependencies and ports.
- `devservices logs <service-name>`: View logs for a specific service.
- `devservices list-services`: List all available Sentry services.
- `devservices list-dependencies <service-name>`: List all dependencies for a service and whether they are enabled/disabled.
- `devservices update` Update devservices to the latest version.
- `devservices purge`: Purge the local devservices cache.
- `devservices toggle <service-name>`: Toggle the runtime for a service between containerized and local.

## Installation

### 1. Add devservices to your requirements.txt

The recommended way to install devservices is through a virtualenv in the requirements.txt. Once that is installed and a devservices config file is added, you should be able to run `devservices up` to begin local development.

```
devservices==1.1.4
```

### 2. Add devservices config files

Each repo should have a `devservices` directory with a `config.yml` file. This file is used to define services, dependencies, and modes. Other files and subdirectories in the `devservices` directory are optional and can be most commonly used for volume mounts.

The configuration file is a yaml file that looks like this:

```yaml
# This is a yaml block that holds devservices specific configuration settings. This is comprised of a few main sections:
# - version: The version of the devservices config file. This is used to ensure compatibility between devservices and the config file.
# - service_name: The name of the service. This is used to identify the service in the config file.
# - dependencies: A list of dependencies for the service. Each dependency is a yaml block that holds the dependency configuration. There are two types of dependencies:
#   - local: A dependency that is defined in the config file. These dependencies do not have a remote field. These dependency definitions are specific to the service and are not defined elsewhere.
#   - remote: A dependency that is defined in the devservices directory in a remote repository. These configs are automatically fetched from the remote repository and installed. Any dependency with a remote field will be treated as a remote dependency. Example: https://github.com/getsentry/snuba/blob/59a5258ccbb502827ebc1d3b1bf80c607a3301bf/devservices/config.yml#L8
# - modes: A list of modes for the service. Each mode includes a list of dependencies that are used in that mode.
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
        mode: default # Optional field, mode to run remote dependency in that defaults to `default`
  modes:
    default: [example-dependency-1, example-remote-dependency]
    custom-mode: [example-dependency-1, example-dependency-2, example-remote-dependency]

# This will be a standard block used by docker compose to define dependencies.
#
# The following fields are important to all dependencies:
# - image: The docker image to use for the dependency.
# - ports: The ports to expose for the dependency. Please only expose ports to localhost(127.0.0.1)
# - healthcheck: The docker healthcheck to use for the dependency.
# - environment: The environment variables to set for the dependency.
# - extra_hosts: The extra hosts to add to the dependency.
# - networks: The networks to add to the dependency. In order for devservices to work properly, the dependency must be on the `devservices` network.
# - labels: The labels to add to the dependency. The `orchestrator=devservices` label is required for devservices to determine a container is managed by devservices.
# - restart: The restart policy to use for the dependency.
#
# These fields are optional:
# - ulimits: The ulimits to set for the dependency. This is useful for setting resource constraints for the dependency.
# - volumes: The volumes to mount for the dependency. This is useful for mounting data volumes for the dependency if data should be persisted between runs. It can also be useful to use a bind mount to mount a local directory into a container. Example of bind mounting clickhouse configs from a local directory https://github.com/getsentry/snuba/blob/59a5258ccbb502827ebc1d3b1bf80c607a3301bf/devservices/config.yml#L44
# - command: The command to run for the dependency. This can override the default command for the docker image.
# For more information on the docker compose file services block, see the docker compose file reference: https://docs.docker.com/reference/compose-file/services/
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
    # Everything below this line is required for devservices to work properly.
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
    # Everything below this line is required for devservices to work properly.
    ports:
      - 127.0.0.1:2345:2345
    extra_hosts:
      host.docker.internal: host-gateway
    networks:
      - devservices
    labels:
      - orchestrator=devservices

# This is a standard block used by docker compose to define volumes.
# For more information, see the docker compose file reference: https://docs.docker.com/reference/compose-file/volumes/
volumes:
  example-dependency-1-data:

# This is a standard block used by docker compose to define networks. Defining the devservices network is required for devservices to work properly. By default, devservices will create an external network called `devservices` that is used to connect all dependencies.
# For more information, see the docker compose file reference: https://docs.docker.com/reference/compose-file/networks/
networks:
  devservices:
    name: devservices
    external: true
```
