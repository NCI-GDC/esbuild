import argparse


class Parser(object):
    """
    Used to build composite parsers from argument group classes
    """

    def __init__(self):
        """
        Builds parser for self only when initialized
        """
        return self.build([self])

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
            group = parser.add_argument_group(**p.group)
            for name, kwargs in p.arguments.items():
                group.add_argument('--{}'.format(name), **kwargs)
        return parser

    @staticmethod
    def log_args(args, parsers, logger):
        """
        Logs arguments and values provided by user
        """
        for parser in parsers:
            args_to_print = [
                arg for arg in args._get_kwargs() if arg[0].replace('_', '-') in parser.arguments
            ]
            logger.info("\t{}:".format(parser.__name__))
            for name, value in args_to_print:
                if any([k in name.lower() for k in ['pass', 'key', 'secret']]):
                    logger.info('{}={}'.format(name, 'VALUE_IS_SECRET'))
                else:
                    logger.info('{}={}'.format(name, value))
