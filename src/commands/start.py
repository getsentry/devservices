from __future__ import annotations


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("start", help="Start a service and its dependencies")
    parser.add_argument("service_name", help="Name of the service to start")
    parser.set_defaults(func=start)


def start(args) -> None:
    """Start a service and its dependencies."""
    service_name = args.service_name
    # Implementation here
    print(f"Starting service: {service_name}")
    # Use docker_compose utility to start the service
