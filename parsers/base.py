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
            args_to_print = [
                arg for arg in args._get_kwargs() if arg[0].replace('_', '-') in p().arguments
            ]
            logger.info("\t{}:".format(p.__name__))
            for name, value in args_to_print:
                if any([k in name.lower() for k in ['pass', 'key', 'secret']]):
                    logger.info('{}={}'.format(name, 'VALUE_IS_SECRET'))
                else:
                    logger.info('{}={}'.format(name, value))
