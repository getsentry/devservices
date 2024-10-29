# devservices

A standalone cli tool used to manage dependencies for services. It simplifies the process of starting, stopping, and managing services for development purposes.

## Overview

`devservices` reads configuration files located in the `devservices` directory of your repository. These configurations define services, their dependencies, and various modes of operation.

## Installation

A system-wide installation can be done by downloading the binary of the latest release

```
PLATFORM=darwin # Options: darwin/linux
INSTALL_DIR="$HOME/.local/bin"
curl -L "https://github.com/getsentry/devservices/releases/download/0.0.4/devservices-$PLATFORM" -o "$INSTALL_DIR/devservices"
chmod +x "$INSTALL_DIR/devservices"
```

Alternatively, if the repository you're working in has a python virtualenv, you can simply add this to the requirements-dev.txt:

```
devservices==0.0.4
```
## Usage

devservices provides several commands to manage your services:

### Commands

NOTE: service-name is an optional parameter. If not provided, devservices will attempt to automatically find a devservices configuration in the current directory in order to proceed.

- `devservices start <service-name>`: Start a service and its dependencies.
- `devservices stop <service-name>`: Stop a service including its dependencies.
- `devservices status <service-name>`: Display the current status of all services, including their dependencies and ports.
- `devservices logs <service-name>`: View logs for a specific service.
- `devservices list-services`: List all available Sentry services.
- `devservices list-dependencies <service-name>`: List all dependencies for a service and whether they are enabled/disabled.
