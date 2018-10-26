import argparse


class Parser:

    @staticmethod
    def build_parser(parsers, description=None):
        parser = argparse.ArgumentParser(description=description)
        for p in parsers:
            parser = p().add_args(parser)
        return parser


class BaseArgs:

    def __init__(self):
        self.parser = self.add_args(argparse.ArgumentParser())
        self.validate(self.parser)

    def add_args(self, parser):
        raise Exception("Not implemented")

    def validate(self, parser):
        """
        Validates that all and only self.args are defined in self.add_args()
        """
        expected_args = {
            arg.replace('--', '').replace('-', '_')
            for arg in parser._option_string_actions
            if arg not in ['-h', '--help']
        }

        if not self.args == expected_args:
            extra_items = self.args - expected_args
            missing_items = expected_args - self.args

            info = '\n'
            if missing_items:
                info += 'Missing items: {}\n'.format(missing_items)
            if extra_items:
                info += 'Extra items: {}\n'.format(extra_items)

            raise Exception(
                '{}: self.args and self.add_args are inconsistent with each other: {}'
                .format(self.__class__, info)
            )
