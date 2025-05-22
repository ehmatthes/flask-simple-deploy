"""Defines the CLI for flask-simple-deploy."""

import click


@click.command()
@click.option(
    "--automate-all",
    is_flag=True,
    help="Automate all aspects of deployment. Create resources, make commits, and run `push` or `deploy` commands.",
)
@click.option(
    "--local-testing",
    is_flag=True,
    help="Local testing, uses no external resources.",
)
def deploy(
    automate_all,
    local_testing,
):
    """Deploy this Flask project using flask-simple-deploy."""
    args = {
        "automate_all": automate_all,
        "local_testing": local_testing,
    }

    # Hand off to deployer.
    from .deploy import main as deploy_main
    deploy_main(args)
