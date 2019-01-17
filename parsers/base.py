import abc
import argparse


class BaseParser(object):
    """
    Abstract base class for argument parsers
    """
    __metaclass__ = abc.ABCMeta

    @abc.abstractproperty
    def group(self):
        """
        Must return dictionary with valid arguments for argparse.add_argument_group()

        Example return:
        {'title': 'Argument group title',
         'description': 'Description for the argument group'}
        """
        pass

    @abc.abstractproperty
    def arguments(self):
        """
        Must return dictionary keyed on the argument name with value being dictionary
        with valid arguments for argparse.add_argument()

        Example return:
        {'my-int-argument': {'help': 'some help', 'default': 1, 'type': int},
         'my-list-argument': {'help': 'some other help', 'nargs': '*'}}

        """
        pass

    def parser(self):
        """
        Returns parser for self only
        """
        return ParserBuilder.build([self])

    @property
    def param_names(self):
        """
        Returns list of parameter names corresponding to self.arguments
        """
        return [arg.replace('-', '_') for arg in self.arguments]

    def get_cmd_list(self, args):
        """
        Returns list of command line arguments and values
        e.g. ["--arg", "v0", "--list-arg", ["v1", "v2"], "--flag-arg"]
        """
        cmd_list = []
        for arg, info in self.arguments.items():
            value = getattr(args, arg.replace('-', '_'))
            arg_action = info.get('action')
            if arg_action:
                # handle "flag argument" case:
                # Don't pass flags when value equals to default one
                if arg_action == 'store_true':
                    if value is False:
                        continue
                elif arg_action == 'store_false':
                    if value is True:
                        continue
                # otherwise pass only the flag
                cmd_list.append("--{}".format(arg))
                continue

            # Populate cmd_list vith arg and value(s)
            if value is not None:
                cmd_list.append("--{}".format(arg))
                if not isinstance(value, list):
                    value = [value]
                cmd_list.extend(map(str, value))
        return cmd_list

    def set_object_params(self, obj, args):
        """
        Given object :obj, set it's parameters corresponding to parser.arguments
        taking values from :args
        """
        for param in self.param_names:
            setattr(obj, param, getattr(args, param))


class ParserBuilder(object):
    """
    Used to build composite parsers from argument group classes
    """

    @staticmethod
    def build(parsers, description=None):
        """
        Assembles a parser using list of {ArgGroup}Args classes
        All of the classes supposed to have 'arguments' and 'group' parameters
        defined
        """
        parser = argparse.ArgumentParser(
            description=description,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        for p in parsers:
            p = p()
            group = parser.add_argument_group(**p.group)
            for name, kwargs in p.arguments.items():
                group.add_argument('--{}'.format(name), **kwargs)
        return parser

    @staticmethod
    def log_args(args, parsers, logger):
        """
        Logs arguments and values provided by user
        """
        for p in parsers:
            args_to_print = [arg for arg in p().param_names]
            logger.info("\t{}:".format(p.__name__))
            for name in args_to_print:
                value = getattr(args, name)
                if any([k in name.lower() for k in ['pass', 'key', 'secret']]):
                    logger.info('{}={}'.format(name, 'VALUE_IS_SECRET'))
                else:
                    logger.info('{}={}'.format(name, value))

    @staticmethod
    def get_cmd_list(args, parsers):
        """
        Returns list of command line arguments corresponding to :parsers
        with values taken from :args
        """
        cmd_list = []
        for p in parsers:
            cmd_list.extend(p().get_cmd_list(args))
        return cmd_list

    @staticmethod
    def get_args_dict(args, parsers):
        """
        Returns dictionary {'argname': 'value'} where values are extracted from :args
        and argnames correspond to :parsers
        """
        args_dict = {}
        for p in parsers:
            for argname in p().param_names:
                args_dict[argname] = getattr(args, argname)
        return args_dict
