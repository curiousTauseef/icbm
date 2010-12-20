#!/usr/bin/python
#
# Copyright 2010 Yext, Inc. All Rights Reserved.

__author__ = "ilia@yext.com (Ilia Mirkin)"

import glob
import functools
import os
import sys

import engine

def cache(f):
    """A decorator to cache results for a given function call.

    Note: The caching is only done on the first argument, usually "self".
    """
    ret = {}
    def _Wrapper(*args, **kwargs):
        self = args[0]
        if self not in ret:
            ret[self] = f(*args, **kwargs)
        return ret[self]
    return _Wrapper

VERBOSE = False

printed = set()
def pdep(a, b):
    """Interceptor for printing dependency links.

    Args:
      a: Source dependency
      b: Destination dependency
    """
    if (a, b) in printed:
        return
    if a == b:
        return
    if VERBOSE:
        print "\"%s\" -> \"%s\"" % (a, b)
    printed.add((a, b))

TOPLEVEL = "_top"

class DataHolder(object):

    """
    Class that is the holder of all objects specified in spec files.
    Keeps track of where they are specified, what they output, and
    intermediates their interactions with the Engine.
    """

    # path:name -> fake-o data holders, which know how to insert things
    # into the engine.
    _registered = {}

    # Set of dependency FullName's whose files have already been loaded.
    _processed = set()

    def __init__(self, module, path, name):
        """Constructor.

        Args:
          module: The module for this target (e.g. Core)
          path: The path for this target
          name: The target name within the path
        """
        self.module = module
        self.path = path
        self.name = name

    def FullName(self):
        """Returns the fully-qualified target name."""
        return "%s=%s:%s" % (self.module, self.path, self.name)

    def Apply(self, e):
        """Inserts any necessary rules into the engine.

        Args:
          e: An engine.Engine instance to insert rules into.

        Returns: A file name which will be generated by the last
        engine rule that was inserted.
        """
        raise NotImplementedError

    def TopApply(self, e):
        """See Apply.

        This function is called instead of Apply when a rule is being
        built explicitly at the command line.
        """
        raise NotImplementedError

    def LoadSpecs(self):
        """Loads spec files needed to resolve this target's dependencies."""
        raise NotImplementedError

    def _LoadSpecs(self, deps):
        """Loads the spec files that define the passed in dependencies.

        Args:
          deps: List of target names that this rule depends on.
        """
        deps = list(self.Canonicalize(deps))
        for dep in deps:
            pdep(self.FullName(), dep)
        while len(deps) > 0:
            depname = deps.pop()
            try:
                LoadTargetSpec(self.module, depname)
            except:
                print "%s: error loading %s=%s" % (self.FullName(), self.module, depname)
                raise
            dep = DataHolder.Get(self.module, depname)
            assert dep, "%s not found by %s:%s" % (depname, self.path, self.name)
            if dep.FullName() in self._processed:
                continue
            self._processed.add(dep.FullName())
            if dep.deps:
                ds = list(dep.Canonicalize(dep.deps))
                deps.extend(ds)
                for d in ds:
                    pdep(dep.FullName(), d)

    def Canonicalize(self, deps):
        """Fully-qualifies any non-fully-qualified dependencies in the list.

        Uses the current module when one isn't provided in the dependecy string.

        Args:
          deps: List of strings of dependency specifiers

        Returns: A list of fully-qualified dependency strings.
        """
        for dep in deps:
            if "=" in dep:
                yield dep
            else:
                yield "%s=%s" % (self.module, dep)


    @classmethod
    def Register(cls, module, path, name, obj):
        """Registers a given target in the global registry."""
        fname = "%s=%s:%s" % (module, path, name)
        assert fname not in cls._registered
        assert isinstance(obj, DataHolder)
        cls._registered[fname] = obj

    @classmethod
    def Get(cls, module, fname):
        """Retrieves a target from the global registry."""
        if "=" not in fname:
            fname = "%s=%s" % (module, fname)
        return cls._registered.get(fname)

    @classmethod
    def Go(cls, targets):
        """Builds everything starting with the given targets as the top-level.

        Args:
          targets: List of string specifiers of targets resolved in top-level
                   scope
        """
        done = set()
        e = engine.Engine()
        target_names = []
        for target in targets:
            holder = cls.Get(TOPLEVEL, target)
            if not holder:
                print >>sys.stderr, "Unknown target", target
                continue
            ret = holder.TopApply(e)
            if ret:
                target_names.append(ret)
        e.ComputeDependencies()
        for target in target_names:
            e.BuildTarget(e.GetTarget(target))
        e.Go()

class JavaBinary(DataHolder):

    """Class that holds a java_binary target."""

    def __init__(self, module, path, name, main, deps, flags):
        DataHolder.__init__(self, module, path, name)
        self.main = main
        self.deps = deps
        self.flags = flags

    @cache
    def Apply(self, e):
        # Build up a list of source files, jars, and data files that
        # we need to get.
        sources = set()
        jars = self.jars = set()
        datas = set()

        deps = list(self.deps)
        processed = set()
        while len(deps) > 0:
            depname = deps.pop()
            dep = DataHolder.Get(self.module, depname)
            assert dep, "%s not found" % depname
            if dep.FullName() in processed:
                continue
            assert isinstance(dep, JavaLibrary)

            dep.Apply(e)

            if dep.files:
                sources.update(dep.files)
            if dep.jars:
                jars.update(dep.jars)
            if dep.data:
                datas.update(dep.data)
            if dep.deps:
                deps.extend(dep.Canonicalize(dep.deps))
            processed.add(dep.FullName())

        c = engine.JavaCompile(self.path, self.name, sources, jars,
                               datas, self.main, self.flags)
        e.AddTarget(c)
        return c.Name()

    TopApply = Apply

    def LoadSpecs(self):
        self._LoadSpecs(self.deps)
        if self.flags:
            DataHolder._LoadSpecs(
                self, ["Core=com/alphaco/util/flags:flag_processor"])


class JavaJar(DataHolder):

    """Class that holds a java_deploy target."""

    def __init__(self, module, path, name, binary):
        DataHolder.__init__(self, module, path, name)
        self.binary = binary

    @cache
    def Apply(self, e):
        dep = DataHolder.Get(self.module, self.binary)
        assert dep, "%s not found" % self.binary
        assert isinstance(dep, JavaBinary)
        dep.Apply(e)
        #name = dep.Apply(e)
        #target = e.GetTarget(name)
        j = engine.JarBuild(self.path, self.name + ".jar", dep.name,
                            dep.jars, dep.main)
        e.AddTarget(j)
        return j.Name()

    TopApply = Apply

    def LoadSpecs(self):
        self._LoadSpecs([self.binary])


class JavaLibrary(DataHolder):

    """Class that holds a java_library target."""

    def __init__(self, module, path, name, files, jars, deps, data):
        DataHolder.__init__(self, module, path, name)
        self.jars = jars
        self.deps = deps
        self.data = data
        self.files = files

    @cache
    def TopApply(self, e):
        sources = set(self.files)
        jars = self.jars = set(self.jars)
        datas = set(self.data)

        deps = list(self.deps)
        processed = set()
        while len(deps) > 0:
            depname = deps.pop()
            dep = DataHolder.Get(self.module, depname)
            assert dep, "%s not found" % depname
            if dep.FullName() in processed:
                continue
            assert isinstance(dep, JavaLibrary)

            dep.Apply(e)

            if dep.files:
                sources.update(dep.files)
            if dep.jars:
                jars.update(dep.jars)
            if dep.data:
                datas.update(dep.data)
            if dep.deps:
                deps.extend(dep.Canonicalize(dep.deps))
            processed.add(dep.FullName())

        c = engine.JavaCompile(self.path, os.path.join(self.path, self.name),
                               sources, jars,
                               datas, None, None)
        e.AddTarget(c)
        return c.Name()

    def Apply(self, e):
        pass

    def LoadSpecs(self):
        if self.deps:
            self._LoadSpecs(self.deps)


class Generate(DataHolder):

    """Class that holds a generate target."""

    def __init__(self, module, path, name, compiler, ins, outs):
        DataHolder.__init__(self, module, path, name)
        self.compiler = compiler
        self.ins = ins
        self.outs = outs

    @cache
    def Apply(self, e):
        target = engine.Generate(self.path, self.name, self.compiler,
                                 self.ins, self.outs)
        e.AddTarget(target)
        return target.Name()

    def LoadSpecs(self):
        pass

class Alias(DataHolder):

    """Class that holds an alias target."""

    def __init__(self, module, path, name, deps):
        DataHolder.__init__(self, module, path, name)
        self.deps = deps

    def Apply(self, e):
        deps = []
        for depname in self.deps:
            dep = DataHolder.Get(self.module, depname)
            deps.append(dep.Apply(e))
        target = engine.Alias(self.path, "__alias_%s" % self.name, deps)
        e.AddTarget(target)
        return target.Name()

    TopApply = Apply

    def LoadSpecs(self):
        self._LoadSpecs(self.deps)

def FixPath(module, path, lst):
    """Computes real/fake paths used by the engine.

    Args:
      module: The current module
      path: The path relative to which the files in lst are given
      lst: A list of files relative to the module/path

    Yields: (fake, real) path tuples for each of the given files. The
    fake path is the path that the file should appear at in the
    output, and the real path is either an absolute path to where the
    file really resides, or it is the fake path in case the file does
    not actually exist.
    """
    if not lst:
        return
    for l in lst:
        fake_path = os.path.join(path, l)
        if module != TOPLEVEL:
            base = "."
            if not fake_path.startswith("jars"):
                base = SRCDIR
            real_path = os.path.join(module, base, fake_path)
        else:
            real_path = fake_path
        if os.path.exists(real_path):
            yield fake_path, os.path.abspath(real_path)
        else:
            yield fake_path, fake_path

def java_library(module, dpath, name, path=None,
                 files=None, jars=None, deps=None, data=None):
    if path:
        dpath = path
    obj = JavaLibrary(module, dpath, name,
                      list(FixPath(module, dpath, files)),
                      list(FixPath(module, dpath, jars)),
                      deps,
                      list(FixPath(module, dpath, data)))
    DataHolder.Register(module, dpath, name, obj)

def java_binary(module, dpath, name, main=None, deps=None,
                flags=False, path=None):
    if path:
        dpath = path
    obj = JavaBinary(module, dpath, name, main, deps, flags)
    DataHolder.Register(module, dpath, name, obj)
    obj = JavaJar(module, dpath, name + "_deploy", obj.FullName())
    DataHolder.Register(module, dpath, name + "_deploy", obj)

def java_deploy(module, dpath, name, binary, path=None):
    if path:
        dpath = path
    obj = JavaJar(module, dpath, name, binary)
    DataHolder.Register(module, dpath, name, obj)

def generate(module, dpath, name, compiler, ins, outs, path=None):
    if path:
        dpath = path
    obj = Generate(module, dpath, name, compiler,
                   list(FixPath(module, dpath, ins)),
                   map(lambda x: x[0], FixPath(module, dpath, outs)))
    DataHolder.Register(module, dpath, name, obj)

def alias(module, path, name, deps):
    obj = Alias(module, path, name, deps)
    DataHolder.Register(module, path, name, obj)

loaded = set()

def LoadTargetSpec(module, target):
    """Loads the spec file that should contain the target in question.

    Args:
      module: The module relative to which the target should be evaluated
      target: The target whose spec file we should load
    """
    # TODO: cache eval results, perhaps reorganize things so that they
    # are cacheable, to avoid reparsing all the files every time.
    if "=" in target:
        module, target = target.split("=", 1)
    assert module, "module unknown for target %s" % target
    assert ":" in target, target
    dirname, tgt = target.split(":")
    if module == TOPLEVEL:
        fn = os.path.join(dirname, "build.spec")
    else:
        base = "."
        if not dirname.startswith("jars"):
            base = SRCDIR
        fn = os.path.join(module, base, dirname, "build.spec")
    if fn in loaded:
        return
    #print "loading", fn
    loaded.add(fn)
    builtins = dict(globals()["__builtins__"])
    del builtins["__import__"]
    d = os.path.dirname(fn)
    def relglob(pattern, excludes=[]):
        """Special glob function that returns a list of paths relative
        to the directory of the spec file.
        """
        return [os.path.relpath(fn, d)
                for fn in glob.glob(os.path.join(d, pattern))
                if os.path.relpath(fn, d) not in excludes]
    scope = {
        "__builtins__": builtins,
        "java_library": functools.partial(java_library, module, dirname),
        "java_binary": functools.partial(java_binary, module, dirname),
        "java_deploy": functools.partial(java_deploy, module, dirname),
        "generate": functools.partial(generate, module, dirname),
        "alias": functools.partial(alias, module, dirname),
        "glob": relglob,
        }
    execfile(fn, scope)

SRCDIR = "src"
