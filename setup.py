from setuptools import find_packages, setup

setup(
    name="devservices",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},

    include_package_data=True,
    install_requires=[
        "pyyaml",
        "sentry-devenv"
    ],
    extras_requires={
        "dev": [
            "mypy",
            "types-pyyaml"
        ],
    },
    entry_points={
        "console_scripts": [
            "devservices=main:main",
        ],
    },
)
