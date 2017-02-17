#!/usr/bin/env python
"""
A helper program for managing the birth, life, and death of a MySQL ramdisk.

Thank you Wayne Moore at http://kotega.com/ for the following article:
"Running MySQL in a ramdisk on OS X"
http://kotega.com/blog/2010/apr/12/mysql-ramdisk-osx/

"""
import json

from optparse import OptionGroup
from optparse import OptionParser
from pathlib import Path
from subprocess import PIPE
from subprocess import Popen


default_settings = {
    'ramdisk_size': 256,  # MB
    'ramdisk_device_path': '/dev/disk3',
    'ramdisk_mount_path': '/Users/brian/ramdisk',
    'mysql_base_path': '/usr/local/Cellar/mysql/5.6.27',
    'mysql_bin_path': '/usr/local/Cellar/mysql/5.6.27/bin',
    'mysql_user': '_mysql',
    'mysql_cnf_path': '/Users/brian'
}


settings_path = Path('~/.mysql-ramdisk')
settings = {}
settings.update(default_settings)
if settings_path.is_file():
    with settings_path.open() as f:
        user_settings = json.load(f)
    settings.update(user_settings.settings)


def pprint(msg):
    print('#### {}'.format(msg))


class SystemControl:

    def __init__(self, settings):
        self.settings = settings

    def _print(self, msg):
        pprint(msg)

    def _run_command(self, command):
        self._print('Starting: {}'.format(command))
        output = Popen(
            command,
            stdout=PIPE,
            shell=True
        ).communicate()
        self._print('Finished: {}'.format(command))
        return output


class Ramdisk(SystemControl):

    def _calc_ramdisk_size(self):
        return self.settings['ramdisk_size'] * 1048576 / 512  # MB * MiB/KB;

    def create_ramdisk(self):
        self._print('Creating ramdisk...')
        ramdisk_size = self._calc_ramdisk_size()
        attach_output = self._run_command('hdiutil attach -nomount ram://{}'.format(ramdisk_size))
        disk_path = attach_output[0].decode('utf-8').strip()
        self._run_command('diskutil eraseVolume HFS+ ramdisk {}'.format(disk_path))
        self.settings['ramdisk_device_path'] = disk_path
        self._print('Done creating ramdisk:{}'.format(disk_path))

    def mount_ramdisk(self):
        self._run_command('mkdir -p {}'.format(self.settings['ramdisk_mount_path']))
        self._run_command('umount /Volumes/ramdisk')
        self._run_command('mount -o noowners -t HFS {} {}'.format(self.settings['ramdisk_device_path'], self.settings['ramdisk_mount_path']))

    def unmount_ramdisk(self):
        self._run_command('umount {}'.format(self.settings['ramdisk_mount_path']))

    def delete_ramdisk(self):
        self._print('Deleting ramdisk...')
        self._run_command('hdiutil detach {}'.format(self.settings['ramdisk_device_path']))
        self._print('Done deleting ramdisk')


class Mysql(SystemControl):

    def install_db(self):
        mysql_path = self.settings['mysql_bin_path']
        mysql_base_path = self.settings['mysql_base_path']
        mysql_user = self.settings['mysql_user']
        ramdisk_mount_point = self.settings['ramdisk_mount_path']
        cnf_dir = self.settings['mysql_cnf_path']

        self._run_command(
            '{mysql_path}/mysql_install_db '
            '--user={mysql_user} '
            '--basedir={mysql_base_path} '
            '--datadir={ramdisk_mount_point}'.format(mysql_path=mysql_path, mysql_base_path=mysql_base_path, mysql_user=mysql_user, ramdisk_mount_point=ramdisk_mount_point)
        )

        my_cnf = """
[mysqld_multi]
mysqld     = {mysql_bin_path}/mysqld_safe
mysqladmin = {mysql_bin_path}/mysqladmin
user       = root

[mysqld8]
socket     = /tmp/mysql.3308.sock
port       = 3308
pid-file   = {ramdisk_mount_point}/mysqld2.pid
datadir    = {ramdisk_mount_point}
user       = {mysql_user}
    """.format(mysql_bin_path=mysql_path, mysql_base_path=mysql_base_path, mysql_user=mysql_user, ramdisk_mount_point=ramdisk_mount_point)
        with open('{}/.my.cnf'.format(cnf_dir), 'w') as f:
            f.write(my_cnf)
        self._print('Done installing db at {}'.format(ramdisk_mount_point))

    def start_db(self):
        mysql_path = self.settings['mysql_bin_path']

        self._run_command('{mysql_path}/mysqld_multi start 8'.format(mysql_path=mysql_path))
        self._print("To log into mysql use: 'msyql --socket=/tmp/mysql.3308.sock [OPTIONS]'")

    def stop_db(self):
        mysql_path = self.settings['mysql_bin_path']

        self._run_command('{mysql_path}/mysqld_multi stop 8'.format(mysql_path=mysql_path))


def _setup_kill_ramdisk_option_group(parser, ramdisk_path):
    # Option group for killing ramdisk:
    group_kill_ramdisk = OptionGroup(parser, 'Options for killing a ramdisk',
                                     'Short for `hdiutil detach /dev/disk1`'
                                     ' with some extra handling and default'
                                     ' location of %s.' % ramdisk_path)
    group_kill_ramdisk.add_option('-k', '--kill-ramdisk', action='store_true',
                                  dest='kill_ramdisk')
    group_kill_ramdisk.add_option('-p', '--path-to-ramdisk', type='string',
                                  default=ramdisk_path,
                                  dest='path_to_ramdisk')
    parser.add_option_group(group_kill_ramdisk)


def _setup_create_ramdisk_option_group(parser, ramdisk_path):
    # Option group for creating ramdisk (and maybe loading it up with mysql):
    group_create_ramdisk = OptionGroup(parser, 'Options for creating a ramdisk',
                                       'Creates a ramdisk, installs,'
                                       ' and starts MySQL')
    group_create_ramdisk.add_option('-c', '--create-ramdisk',
                                    action='store_true',
                                    dest='create_ramdisk',
                                    help='create ramdisk')
    group_create_ramdisk.add_option('-s',
                                    '--ramdisk-size',
                                    default=settings['ramdisk_size'],
                                    help="Size should be specified in MB.",
                                    type='int',
                                    dest='ramdisk_size')
    # I group installing and starting the mysql db here out of convenience.
    # TODO create an option for Solr here too.
    group_create_ramdisk.add_option('-m', '--with-mysql',
                                    action='store_true',
                                    dest='with_mysql')

    parser.add_option_group(group_create_ramdisk)


option_groups = {
    'kill': _setup_kill_ramdisk_option_group,
    'create': _setup_create_ramdisk_option_group
}


def setup_option_groups(parser, group_name):
    global settings
    option_groups[group_name](parser, settings['ramdisk_device_path'])


def main():
    usage = "usage: %prog [options] arg1 arg2"
    parser = OptionParser(usage=usage)
    setup_option_groups(parser, 'kill')
    setup_option_groups(parser, 'create')

    (options, args) = parser.parse_args()

    ramdisk = Ramdisk(settings)
    mysql = Mysql(settings)

    if options.create_ramdisk:
        ramdisk.create_ramdisk()
        ramdisk.mount_ramdisk()
        if options.with_mysql:
            mysql.install_db()
            mysql.start_db()
    elif options.kill_ramdisk:
        mysql.stop_db()
        ramdisk.unmount_ramdisk()
        ramdisk.delete_ramdisk()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
