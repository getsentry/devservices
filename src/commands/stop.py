from __future__ import annotations


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("stop", help="Stop a service and its dependencies")
    parser.add_argument("service_name", help="Name of the service to stop")
    parser.set_defaults(func=stop)


def stop(args) -> None:
    """Stop a service and its dependencies."""
    service_name = args.service_name
    # Implementation here
    print(f"Stopping service: {service_name}")
    # Use docker_compose utility to stop the service
