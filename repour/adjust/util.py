# flake8: noqa
import argparse
import asyncio
import logging
import os
import re
from xml.dom import minidom

from repour import asutil, exception

from opentelemetry import trace
from opentelemetry.trace import format_span_id, format_trace_id
from opentelemetry.trace.span import TraceFlags, TraceState

from repour.lib.logs import log_util

logger = logging.getLogger(__name__)

REPOUR_JAVA_KEY = "-DRepour_Java="
SERVICE_BUILD_CATEGORY = "SERVICE"

stdout_options = asutil.process_stdout_options
stderr_options = asutil.process_stderr_options


def get_removed_repos(work_dir, parameters):
    """
    Parses the filename of the removed repos backup file from the parameters list and if there
    is one, it reads the list of repos and returns it.
    """
    result = []

    pattern = re.compile("-DrepoRemovalBackup[ =](.+)")
    for parameter in parameters:
        m = pattern.match(parameter)
        if m is not None:
            filepath = os.path.join(work_dir, m.group(1))
            logger.debug(
                "Files and folders in the work directory:\n  %s", os.listdir(work_dir)
            )

            if os.path.exists(filepath):
                tree = minidom.parse(filepath)
                for repo_elem in tree.getElementsByTagName("repository"):
                    repo = {
                        "releases": True,
                        "snapshots": True,
                        "name": "",
                        "id": "",
                        "url": "",
                    }
                    for enabled_elem in repo_elem.getElementsByTagName("enabled"):
                        if enabled_elem.parentNode.localName in [
                            "releases",
                            "snapshots",
                        ]:
                            bool_value = enabled_elem.childNodes[0].data == "true"
                            repo[enabled_elem.parentNode.localName] = bool_value
                    for tag in ["id", "name", "url"]:
                        for elem in repo_elem.getElementsByTagName(tag):
                            if elem.childNodes:
                                repo[tag] = elem.childNodes[0].data
                    result.append(repo)
                break
            else:
                logger.info(
                    "File %s does not exist. It seems no repositories were removed",
                    filepath,
                )

    logger.info("Removed repos are: " + str(result))
    return result


def is_temp_build(adjustspec):
    """For temp build to be active, we need to both provide a 'is_temp_build' key
    in our request and its value must be true

    return: :bool: whether temp build feature enabled or not
    """
    return has_key_true(adjustspec, "tempBuild")


def is_alignment_preference(adjustspec, value):
    """For temp build to be active, we need to both provide a 'is_temp_build' key
    in our request and its value must be true

    return: :bool: whether temp build feature enabled or not
    """
    return has_key_value(adjustspec, "alignmentPreference", value)


def has_key_true(adjustspec, key):
    """Checks if the key is in the adjustspec and if the key is True.

    return: :bool: if the key is set and is True
    """
    if (key in adjustspec) and adjustspec[key] is True:
        return True
    else:
        return False


def has_key_value(adjustspec, key, value):
    """Checks if the key is in the adjustspec and if the key has given value.

    return: :bool: if the key is set and is True
    """
    if (key in adjustspec) and adjustspec[key] == value:
        return True
    else:
        return False


def get_build_version_suffix_prefix(build_category_config, temp_build_enabled):
    """Generate the prefix of version suffix (i.e. suffix prefix) from the adjust request.

    If the suffix prefix is set *AND* the one of the special build types is active then
    this function returns the value of the suffix prefix.

    Otherwise it will return None
    """
    temporary_prefix = "temporary"

    suffix_prefix = build_category_config["suffix_prefix"]

    if temp_build_enabled:
        if suffix_prefix:
            suffix_prefix = suffix_prefix + "-" + temporary_prefix
        else:
            suffix_prefix = temporary_prefix

    return suffix_prefix


def strip_temporary_from_prefix(suffix_prefix: str):
    """Strip "-temporary" portion from suffix_prefix generated by get_build_version_suffix_prefix

    Returns stripped suffix_prefix
    """
    temporary_prefix = "temporary"

    return suffix_prefix.removesuffix(temporary_prefix).rstrip("-")


def get_extra_parameters(extra_adjust_parameters, flags=("-f", "--file")):
    """
    Get the extra build configuration parameters from PNC
    If the parameters contain '<flag>=<folder>/pom.xml', then extract that folder
    and remove that <flag> option from the list of extra params.
    In PME 2.11 and PME 2.12, there is a bug where that option causes the file target/pom-manip-ext-result.json
    to be badly generated. Fixed in PME 2.13+
    See: PRODTASKS-361

    'flags' (:tuple:) specify which options to check for the extra parameters. By default it is '-f' and '--file', but can be adjusted

    Returns: tuple<list<string>, string>: list of params(minus the <flag> option), and folder where to run PME
    If '<flag>' option not used, the folder will be an empty string
    """
    subfolder = ""

    paramsString = extra_adjust_parameters.get("ALIGNMENT_PARAMETERS", None)
    if paramsString is None:
        return [], subfolder
    else:

        parser = argparse.ArgumentParser()
        parser.add_argument(*flags)
        (options, remaining_args) = parser.parse_known_args(paramsString.split())

        # remove any leading dash
        option_title = re.sub(r"^-*", "", flags[-1])

        if getattr(options, option_title) is not None:
            subfolder = getattr(options, option_title)

        return remaining_args, subfolder


def verify_folder_exists(folder, error_msg):
    """
    Checks if the folder exists and it is a folder. If not, a exception.CommandError is thrown
    """
    if os.path.exists(folder) and os.path.isdir(folder):
        # all ok! do nothing!
        pass
    else:
        if not os.path.exists(folder):
            raise exception.CommandError(
                error_msg, [], 10, stdout=error_msg, stderr=error_msg
            )
        else:
            raise exception.CommandError(
                error_msg, [], 10, stdout=error_msg, stderr=error_msg
            )


def get_jvm_from_extra_parameters(extra_parameters):
    """
    If repour JVM option specified, return the option value. Otherwise return None
    """

    for parameter in extra_parameters:

        if REPOUR_JAVA_KEY in parameter:
            return parameter.replace(REPOUR_JAVA_KEY, "")
    else:
        return None


def get_param_value(name, params1, params2=[], params3=[]):
    """
    Searches for the given param name in given arrays and returns the value of the first occurrence. The param name must
    match completely, so you have to pass it along with "-D" if it is in the arrays.
    """
    for params in [params1, params2, params3]:
        for param in params:
            if param.startswith(name + "="):
                return param.replace(name + "=", "")
    return None


async def print_java_version(java_bin_dir=""):

    if java_bin_dir and java_bin_dir.endswith("/"):
        command = java_bin_dir + "java"
    elif java_bin_dir:
        command = java_bin_dir + "/java"
    else:
        command = "java"

    expect_ok = asutil.expect_ok_closure()
    output = await expect_ok(
        cmd=[command, "-version"],
        desc="Failed getting Java version",
        cwd=".",
        stdout=stdout_options["text"],
        stderr=stderr_options["stdout"],
        print_cmd=True,
    )
    logger.info(output)


class UserContextFormatter:
    def __init__(self, mdc_dict):
        self.mdc_dict = mdc_dict

    def as_env_dict(self):
        return {
            "LOG_USER_ID": self.mdc_dict["log-user-id"],
            "LOG_REQUEST_CONTEXT": self.mdc_dict["log-request-context"],
            "LOG_PROCESS_CONTEXT": self.mdc_dict["log-process-context"],
            "LOG_EXPIRES": self.mdc_dict["log-expires"],
            "LOG_TMP": self.mdc_dict["log-tmp"],
            "TRACE_ID": self.mdc_dict["trace-id"],
            "SPAN_ID": self.mdc_dict["span-id"],
            "TRACEPARENT": self.mdc_dict["traceparent"],
        }

    def as_key_value_string(self):
        result = ""
        for key, value in self.mdc_dict.items():
            result += key + ":" + value + ","

        return result


async def generate_user_context() -> UserContextFormatter:
    """Returns a string of key:value,key:value"""

    # get the current span, created by flask
    current_span = trace.get_current_span()
    if current_span.get_span_context().is_valid:
        trace_id = format_trace_id(current_span.get_span_context().trace_id)
        span_id = format_span_id(current_span.get_span_context().span_id)
        trace_flags = current_span.get_span_context().trace_flags
    else:
        trace_id = log_util.get_mdc_value_in_task("trace_id")
        span_id = log_util.get_mdc_value_in_task("span_id")
        trace_flags = TraceFlags.get_default()

    sampled = (TraceFlags.SAMPLED & trace_flags) != 0

    if trace_id is not None:
        current_traceparent = "00-{}-{}-{}".format(
            trace_id, span_id, "01" if sampled else "00"
        )
    else:
        current_traceparent = ""

    current_task = asyncio.current_task()

    mdc_headers = {
        "log-user-id": current_task.mdc["userId"],
        "log-request-context": current_task.mdc["requestContext"],
        "log-process-context": current_task.mdc["processContext"],
        "log-expires": current_task.mdc["expires"],
        "log-tmp": current_task.mdc["tmp"],
        "trace-id": current_task.mdc["trace_id"],
        "span-id": current_task.mdc["span_id"],
        "traceparent": current_traceparent,
    }

    return UserContextFormatter(mdc_headers)
