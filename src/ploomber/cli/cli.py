from pathlib import Path
import os
import difflib as dl
import sys

import click

from ploomber.spec import DAGSpec
from ploomber import __version__
from ploomber import cli as cli_module
from ploomber import scaffold as _scaffold
from ploomber_scaffold import scaffold as scaffold_project

from ploomber.table import Table
from ploomber.telemetry import telemetry


@click.group()
@click.version_option(version=__version__)
def cli():
    """Ploomber command line interface.
    """
    pass  # pragma: no cover


@cli.command()
@click.option(
    '--conda/--pip',
    '-c/-p',
    is_flag=True,
    default=None,
    help='Use environment.yaml/requirements.txt for dependencies',
)
@click.option(
    '--package',
    '-P',
    is_flag=True,
    help='Use package template (creates setup.py)',
)
@click.option(
    '--empty',
    '-E',
    is_flag=True,
    help='Create a pipeline.yaml with no tasks',
)
@click.option(
    '--entry-point',
    '-e',
    default=None,
    help='Entry point to add tasks. Invalid if other flags present',
)
@click.argument('name', required=False)
def scaffold(name, conda, package, entry_point, empty):
    """Create a new project / Create task source files

    $ ploomber scaffold myproject

    $ cd myproject

    Add tasks to pipeline.yaml. Then, to create the source files:

    $ ploomber scaffold
    """
    template = '-e/--entry-point is not compatible with {flag}'
    user_passed_name = name is not None

    if entry_point and name:
        err = '-e/--entry-point is not compatible with the "name" argument'
        telemetry.log_api("scaffold_error",
                          metadata={
                              'type': 'entry_and_name',
                              'exception': err,
                              'argv': sys.argv
                          })
        raise click.ClickException(err)

    if entry_point and conda:
        err = template.format(flag='--conda')
        telemetry.log_api("scaffold_error",
                          metadata={
                              'type': 'entry_and_conda_flag',
                              'exception': err,
                              'argv': sys.argv
                          })
        raise click.ClickException(err)

    if entry_point and package:
        err = template.format(flag='--package')
        telemetry.log_api("scaffold_error",
                          metadata={
                              'type': 'entry_and_package_flag',
                              'exception': err,
                              'argv': sys.argv
                          })
        raise click.ClickException(err)

    if entry_point and empty:
        err = template.format(flag='--empty')
        telemetry.log_api("scaffold_error",
                          metadata={
                              'type': 'entry_and_empty_flag',
                              'exception': err,
                              'argv': sys.argv
                          })
        raise click.ClickException(err)

    # try to load a dag by looking in default places
    if entry_point is None:
        loaded = _scaffold.load_dag()
    else:
        try:
            loaded = (
                DAGSpec(entry_point, lazy_import='skip'),
                Path(entry_point).parent,
                Path(entry_point),
            )
        except Exception as e:
            telemetry.log_api("scaffold_error",
                              metadata={
                                  'type': 'dag_load_failed',
                                  'exception': str(e),
                                  'argv': sys.argv
                              })
            raise click.ClickException(e) from e

    if loaded:
        if user_passed_name:
            click.secho(
                "The 'name' positional argument is "
                "only valid for creating new projects, ignoring...",
                fg='yellow')

        # existing pipeline, add tasks
        spec, _, path_to_spec = loaded
        _scaffold.add(spec, path_to_spec)

        telemetry.log_api("ploomber_scaffold",
                          metadata={
                              'type': 'add_task',
                              'argv': sys.argv,
                              'dag': loaded,
                          })
    else:
        # no pipeline, create base project
        telemetry.log_api("ploomber_scaffold",
                          metadata={
                              'type': 'base_project',
                              'argv': sys.argv
                          })
        scaffold_project.cli(project_path=name,
                             conda=conda,
                             package=package,
                             empty=empty)


@cli.command()
@click.option('--use-lock/--no-use-lock',
              '-l/-L',
              default=None,
              help=('Use lock/regular files. If not present, uses any '
                    'of them, prioritizing lock files'))
@click.option('--create-env',
              '-e',
              is_flag=True,
              help=('Create a new environment, otherwise install in the '
                    'current environment'))
@click.option(
    '--use-venv',
    '-v',
    is_flag=True,
    help='Use Python\'s venv module (ignoring conda if installed)',
)
def install(use_lock, create_env, use_venv):
    """
    Install dependencies
    """
    cli_module.install.main(use_lock=use_lock,
                            create_env=create_env,
                            use_venv=use_venv)


@cli.command()
@click.option('-n', '--name', help='Example to download', default=None)
@click.option('-f', '--force', help='Force examples download', is_flag=True)
@click.option('-o', '--output', help='Target directory', default=None)
@click.option('-b', '--branch', help='Git branch to use.', default=None)
def examples(name, force, branch, output):
    """Download examples

    List:

    $ ploomber examples

    Download:

    $ ploomber examples -n type/example -o directory

    Download ml-basic example:

    $ ploomber examples -n templates/ml-basic -o my-pipeline
    """
    try:
        cli_module.examples.main(name=name,
                                 force=force,
                                 branch=branch,
                                 output=output)
    except click.ClickException:
        raise
    except Exception as e:
        telemetry.log_api("examples_error",
                          metadata={
                              'type': 'runtime_error',
                              'exception': str(e),
                              'argv': sys.argv
                          })
        raise RuntimeError(
            'An error happened when executing the examples command. Check out '
            'the full error message for details. Downloading the examples '
            'again or upgrading Ploomber may fix the '
            'issue.\nDownload: ploomber examples -f\n'
            'Update: pip install ploomber -U\n'
            'Update [conda]: conda update ploomber -c conda-forge') from e


def _exit_with_error_message(msg):
    click.echo(msg, err=True)
    sys.exit(2)


def cmd_router():
    cmd_name = None if len(sys.argv) < 2 else sys.argv[1]

    # These are parsing dynamic parameters and that's why we're isolating it.
    custom = {
        'build': cli_module.build.main,
        'plot': cli_module.plot.main,
        'task': cli_module.task.main,
        'report': cli_module.report.main,
        'interact': cli_module.interact.main,
        'status': cli_module.status.main,
        'nb': cli_module.nb.main,
    }

    # users may attempt to run execute/run, suggest to use build instead
    # users may make typos when running one of the commands
    # suggest correct spelling on obvious typos

    if cmd_name in custom:
        # NOTE: we don't use the argument here, it is parsed by _main
        # pop the second element ('entry') to make the CLI behave as expected
        sys.argv.pop(1)
        # Add the current working directory, this is done automatically when
        # calling "python -m ploomber.build" but not here ("ploomber build")
        sys.path.insert(0, os.path.abspath('.'))
        fn = custom[cmd_name]
        fn()
    else:
        suggestion = dl.get_close_matches(
            cmd_name,
            ['build', 'interact', 'report', 'status', 'task', 'examples'],
            cutoff=0.1,
            n=1)
        if suggestion in [
                'build', 'interact', 'report', 'status', 'task', 'examples'
        ]:
            telemetry.log_api("unsupported_build_cmd",
                              metadata={
                                  'cmd_name': cmd_name,
                                  'suggestion': suggestion,
                                  'argv': sys.argv
                              })
            _exit_with_error_message(
                "Try 'ploomber --help' for help.\n\n"
                f"Error: {cmd_name!r} is not a valid command."
                f" Did you mean {suggestion!r}?")
        else:
            if cmd_name not in ['examples', 'scaffold', 'install']:
                telemetry.log_api("unsupported-api-call",
                                  metadata={'argv': sys.argv})
            cli()


# the commands below are handled by the router,
# those are a place holder to show up in ploomber --help
@cli.command()
def build():
    """Build pipeline
    """
    pass  # pragma: no cover


@cli.command()
def status():
    """Show pipeline status
    """
    pass  # pragma: no cover


@cli.command()
def plot():
    """Plot pipeline
    """
    pass  # pragma: no cover


@cli.command()
def task():
    """Interact with specific tasks
    """
    pass  # pragma: no cover


@cli.command()
def report():
    """Generate pipeline report
    """
    pass  # pragma: no cover


@cli.command()
def interact():
    """Start an interactive session
    """
    pass  # pragma: no cover


@cli.command()
def nb():
    """Manage scripts and notebooks
    """
    pass  # pragma: no cover


@cli.group()
def cloud():
    """Ploomber cloud command line interface.
    """
    pass  # pragma: no cover


@cloud.command()
@click.argument('user_key', required=True)
def set_key(user_key):
    """
    This function sets the cloud API Key. It validates it's a valid key.
    If the key is valid, it stores it in the user config.yaml file.
    """
    cli_module.cloud.set_key(user_key)


@cloud.command()
def get_key():
    """
    This function gets the cloud API Key. It retrieves it from the user
    config.yaml file. Returns the key if exist, returns None if doesn't exist.
    """
    key = cli_module.cloud.get_key()
    if key:
        print('This is your cloud API key: {}'.format(key))


@cloud.command()
@click.argument('pipeline_id', default=None, required=False)
@click.option('-v', '--verbose', default=False, is_flag=True, required=False)
def get_pipelines(pipeline_id, verbose):
    """
    Use this to get the state of your pipelines, specify a single pipeline_id
    to get it's state, when not specified, pulls all of the pipelines.
    You can pass the `latest` tag, instead of pipeline_id to get the latest.
    To get a detailed view pass the verbose flag.
    Returns a list of pipelines is succeeds, an Error string if fails.
    """
    pipeline = cli_module.cloud.get_pipeline(pipeline_id, verbose)
    if isinstance(pipeline, list) and pipeline:
        pipeline = Table.from_dicts(pipeline, complete_keys=True)
    print(pipeline)


@cloud.command()
@click.argument('pipeline_id', required=True)
@click.argument('status', required=True)
@click.argument('log', default=None, required=False)
@click.argument('dag', default=None, required=False)
@click.argument('pipeline_name', default=None, required=False)
def write_pipeline(pipeline_id, status, log, pipeline_name, dag):
    """
    This function writes a  pipeline, pipeline_id & status are required.
    You can also add logs and a pipeline name.
    Returns a string with pipeline id if succeeds, an Error string if fails.
    """
    print(
        cli_module.cloud.write_pipeline(pipeline_id, status, log,
                                        pipeline_name, dag))


@cloud.command()
@click.argument('pipeline_id', required=True)
def delete_pipeline(pipeline_id):
    """
    This function deletes a pipeline, pipeline_id is required.
    Returns a string with pipeline id if succeeds, an Error string if fails.
    """
    print(cli_module.cloud.delete_pipeline(pipeline_id))
