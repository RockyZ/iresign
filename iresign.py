#!/usr/bin/env python3
# coding: utf-8
"""
    iResign
    ~~~~~~~

    iResign is a tool for recodesigning iOS applications.  There are many
    scripts with similar functionality but iResign is my very own bicycle.

    The script written just for fun. I just want to print some useful info
    during recodesigning and this script does it well! Moreover, it's Python
    so you can easy to extend it in your own way.

    :copyright: (c) 2013, Igor Kalnitsky <igor@kalnitsky.org>
    :license: BSD, see LICENSE for details.
"""
import os
import sys
import shutil
import argparse
import plistlib
import tempfile
import subprocess


__version__ = '0.2.2'


PY2 = sys.version_info[0] == 2
if PY2:
    write_plist_to_string = plistlib.writePlistToString

    def read_plist_from_string(data):
        """
        Parse a given data and return a plist object. If a given data has a
        binary signature it will be striped before parsing.
        """
        # strip binary signature if exists
        beg, end = '<?xml', '</plist>'
        beg, end = data.index(beg), data.index(end) + len(end)
        data = data[beg: end]

        return plistlib.readPlistFromString(data)
else:
    write_plist_to_string = plistlib.writePlistToBytes

    def read_plist_from_string(data):
        """
        Parse a given data and return a plist object. If a given data has a
        binary signature it will be striped before parsing.
        """
        data = data.decode('latin1')

        # strip binary signature if exists
        beg, end = '<?xml', '</plist>'
        beg, end = data.index(beg), data.index(end) + len(end)
        data = data[beg: end]

        data = data.encode('latin1')
        return plistlib.readPlistFromBytes(data)


def read_provisioning_profile(filename):
    """
    Read and parse a given filename as provisioning profile, and return
    a `dict` with profile's attributes.
    """
    content = {}
    with open(filename, 'rb') as f:
        content = read_plist_from_string(f.read())

    return {
        'filename':      filename,
        'uuid':          content['UUID'],
        'name':          content['Name'],
        'app_id_prefix': content['ApplicationIdentifierPrefix'][0],
        'entitlements':  content['Entitlements'],
        'app_id':        content['Entitlements']['application-identifier'],
        'aps_env':       content['Entitlements'].get('aps-environment', None),
        'task_allow':    content['Entitlements']['get-task-allow'],
    }


def read_application(filename):
    """
    Read iOS application file (.app) and return a `dict` with application's
    attributes.
    """
    provision = os.path.join(filename, 'embedded.mobileprovision')
    return {
        'filename':   os.path.abspath(filename),
        'provision':  read_provisioning_profile(provision),
    }


def generate_entitlements(provision_entitlements, app):
    """
    Merge provision entitlements with application one. We really need
    to save a `keychain-access-groups` from the embedded entitlements.
    """
    # get keychain-access-groups from the application
    command = 'codesign --display --entitlements - "{app}" 2> /dev/null'
    p = subprocess.Popen(command.format(
        app=app['filename']
    ), shell=True, stdout=subprocess.PIPE)
    entitlements = read_plist_from_string(p.communicate()[0])
#     access_groups = entitlements.get('keychain-access-groups')

    # use application keychain-acccess-groups in the new entitlements
#     if access_groups:
#         provision_entitlements['keychain-access-groups'] = access_groups
    return provision_entitlements


def recodesign(app, provision, identity, dryrun=False, verbose=False):
    """
    ReCodeSign a given app with a given provision and identity pair.
    """
    # embeding a new provisioning profile
    if not dryrun:
        print('embeding a new provisioning profile:', provision['filename'], ' -> ', app['provision']['filename'])
        shutil.copyfile(provision['filename'], app['provision']['filename'])

    for framework_path in frameworks_in_app(app):
        recodesign_frameworks(framework_path, identity, dryrun=dryrun, verbose=verbose)

    # generate a new entitlements
    entitlements = tempfile.NamedTemporaryFile(suffix=".plist", delete=False)
    print('generate a new entitlements:', entitlements.name)
    entitlements_dict = generate_entitlements(provision['entitlements'], app)
    entitlements.write(write_plist_to_string(entitlements_dict))
    entitlements.close()

    # recodesign
    command = 'codesign {dryrun} -f -s "{identity}" --entitlements "{entitlements}" ' \
              '--no-strict "{app}" {verbose}'
    command = command.format(
        dryrun='--dryrun' if dryrun else '',
        identity=identity,
        entitlements=entitlements.name,
        app=app['filename'],
        verbose='--verbose' if verbose else ''
    )
    print('codesigning: \n  %s' % command)
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()

    if verbose:
        out, err = p.communicate()
        if out:
            print(out)
        if err:
            print(err)

    if p.returncode == 0:
        print('codesign success.')
    else:
        print('codesign failed.')
        exit(1)

    command = 'codesign --verify "{app}" {verbose}'
    command = command.format(
        app=app['filename'],
        verbose='--verbose' if verbose else ''
    )
    print('verifying codesign: \n  %s' % command)
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()

    if verbose:
        out, err = p.communicate()
        if out:
            print(out)
        if err:
            print(err)

    if p.returncode == 0:
        print('verify codesign pass.')
    else:
        print('verify codesign failed.')
        exit(1)

    os.unlink(entitlements.name)

def show_provision_info(provision):
    """
    Print information about a given provisioning profile.
    """
    print('')
    print('     Provision :: %s' % os.path.basename(provision['filename']))
    print('')
    print('          UUID:   %s' % provision['uuid'])
    print('          Name:   %s' % provision['name'])
    print('        App ID:   %s' % provision['app_id'])
    print('       APS Env:   %s' % provision['aps_env'])
    print('    Task Allow:   %s' % provision['task_allow'])
    print('')

def recodesign_frameworks(framework_path, identity, dryrun=False, verbose=False):

    dylib = dylib_name_in_framework(framework_path)

    if not dylib:
        print('not found dylib in %s' % framework_path)
        return

    command = 'codesign {dryrun} -f -s "{identity}" --preserve-metadata=identifier,entitlements ' \
              '"{dylib}" {verbose}'

    command = command.format(
        dryrun='--dryrun' if dryrun else '',
        identity=identity,
        dylib=os.path.join(framework_path, dylib),
        verbose='--verbose' if verbose else ''
    )

    print('codesign framework: \n  %s' % command)
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p.wait()

    if verbose:
        out, err = p.communicate()
        if out:
            print(out)
        if err:
            print(err)

    if p.returncode == 0:
        print('verify codesign pass:', framework_path)
    else:
        print('verify codesign failed:', framework_path)
        exit(1)

def dylib_name_in_framework(framework_path):
    content = {}
    with open(os.path.join(framework_path, 'Info.plist'), 'rb') as f:
        content = plistlib.readPlist(f)

    return content['CFBundleExecutable'] 

def frameworks_in_app(app):
    return [root for root, dirs, files in os.walk(app['filename']) if root.endswith('framework')]

def main():
    """
    iResign's entry point.
    """
    # parse command line arguments
    arguments = parse_arguments()

    # get main three components for recodesigning
    application = read_application(arguments.app)
    provision = read_provisioning_profile(arguments.provisioning_profile)
    identity = arguments.identity

    # recodesigning!
    print('* Recodesigning :: {old} => {new}'.format(
        old=application['provision']['name'], new=provision['name']))

    # print verbose information
    if arguments.verbose:
        show_provision_info(application['provision'])
        show_provision_info(provision)

    recodesign(application, provision, identity, arguments.dryrun, verbose=arguments.verbose)
    print('* done!')


def parse_arguments():
    """
    Parse command line arguments, check and return them if all is ok.
    """
    parser = argparse.ArgumentParser(
        description='iResign is a tool for recodesigning iOS applications.')

    parser.add_argument('app', help='the path to the iOS application file')

    parser.add_argument('provisioning_profile',
                        help='the path to the provisioning profile')

    parser.add_argument('identity', nargs='?', default='iPhone Developer',
                        help='the signing identity')

    parser.add_argument('-d', '--dryrun', dest='dryrun', action='store_true',
                        help='test posibility of recodesigning')

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='show info about provisioning profiles')

    return parser.parse_args()


if __name__ == '__main__':
    main()
