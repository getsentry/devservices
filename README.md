# devservices

A standalone cli tool used to manage dependencies for services. It simplifies the process of starting, stopping, and managing services for development purposes.

## Overview

`devservices` reads configuration files located in the `devservices` directory of your repository. These configurations define services, their dependencies, and various modes of operation.

## Installation

The recommended way to install devservices is through a virtualenv in the requirements.txt.

```
devservices==1.0.2
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
- `devservices update` Update devservices to the latest version.
- `devservices purge`: Purge the local devservices cache.
