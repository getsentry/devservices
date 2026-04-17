# TODO

## Per-dependency healthcheck_timeout for remote sub-services

`healthcheck_timeout` set on a dependency only applies to that dependency's containers when it is a direct local compose service. For remote dependencies (e.g. `snuba`), the timeout is applied to all of snuba's sub-containers as a group using the calling service's fallback (`HEALTHCHECK_TIMEOUT`). There is currently no way to configure a custom timeout for an individual sub-container (e.g. `kafka` inside `snuba`) from the calling service's `config.yml`.

To fix this properly, the timeout would need to be threaded through the remote dependency resolution path so that a service like snuba can declare its own per-sub-service timeouts in its own `config.yml` and have those respected when snuba is brought up as a dependency of another service.
