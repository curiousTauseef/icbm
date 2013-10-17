#!/usr/bin/python

import ConfigParser
import optparse
import sys

VERBOSE = False
MODULE_PATHS = ["lib", "src"]
FLAGS_BY_DEFAULT = False
PROTOBUF_JAVA = "lib=:protobuf-java-2.5.0"
VALID_TLDS = "com org net javax"

# Avoid having to declare all the variables as global in init.
config = sys.modules[__name__]

def init():
    parser = optparse.OptionParser()
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose")
    (options, args) = parser.parse_args()
    config.VERBOSE = options.verbose

    conf = ConfigParser.SafeConfigParser(allow_no_value=True)
    # Module paths (the options of the modules section) must be case sensitive.
    conf.optionxform = str
    conf.read("icbm.cfg")
    if conf.has_section("modules"):
        config.MODULE_PATHS = [path for path, _ in conf.items("modules")]
    if conf.has_option("java", "flags_by_default"):
        config.FLAGS_BY_DEFAULT = conf.getboolean(
            "java", "flags_by_default")
    if conf.has_option("java", "valid_tlds"):
        config.VALID_TLDS = conf.get("java", "valid_tlds")
    if conf.has_option("proto", "protobuf_java"):
        config.PROTOBUF_JAVA = conf.get("proto", "protobuf_java")

    return args

# This is a little dangerous, but even if the module happens to be
# double-initialized, this function should be idempotent.
ARGS = init()
