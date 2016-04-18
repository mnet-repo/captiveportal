# Add an iptables rule

import re
import socket
from io import BytesIO
from logging import getLogger, DEBUG, WARN, INFO

try:
    from configparser import RawConfigParser
except ImportError:
    from ConfigParser import RawConfigParser

from portal import logHandler, logFormatter

# Try to import arping for mac_from_ip()
try:
    from sh import arping
except ImportError:
    pass

# By default run iptables through sudo, so the worker process must run with
# a user that is allowed to execute iptables commands with NOPASSWD.
from sh import sudo, ErrorReturnCode

def run(arg):
    # Some info from the plugin dispatcher.
    environ = arg['environ']
    plugin_config = arg['config']

    config = RawConfigParser(defaults=plugin_config)
    config.add_section('iptables')
    config._sections['iptables'] = plugin_config

    # Setup plugin logging
    l = getLogger('plugin_iptables')
    l.addHandler(logHandler)
    if config.getboolean('iptables', 'debug'):
        l.setLevel(DEBUG)
        l.debug('debug logging enabled')

    client_ip = environ.get(
        'HTTP_X_FORWARDED_FOR',
        environ.get('REMOTE_ADDR')
    )
    client_mac = None
    error_msg = None
    iptables_failed = False

    # Verify IP
    try:
        socket.inet_aton(client_ip)
    except socket.error:
        l.error('Client IP-address is invalid')
        return {
            'error': str(e),
            'failed': True
        }

    # Attempt to get client HW address first.
    try:
        client_mac = mac_from_ip(
            l,
            config.get('iptables', 'arping'),
            client_ip
        )
    except Exception as e:
        l.warn('Failed to get client HW address: {error}'.format(
            error=str(e)
        ))
        error_msg = str(e)
        pass

    # If HW address was found, use it now.
    if client_mac:
        l.debug('Found client HW address: {hw}'.format(
            hw=client_mac
        ))

        # Create tuple out of iptables command
        iptables_mac = config.get('iptables', 'iptables_mac').format(
            mac_address=client_mac
        )
        iptables_mac = tuple(iptables_mac.split(' '))

        output = BytesIO()
        error = BytesIO()
        try:
            rc = sudo.iptables(iptables_mac, _out=output, _err=error)

            if rc.exit_code == 0:
                l.debug('Created iptables MAC rule successfully')
                return {
                    'error': error_msg,
                    'failed': False
                }
        except ErrorReturnCode:
            error.seek(0)
            error_msg = error.read()
            l.warn('{cmd}: exited badly: {error}'.format(
                cmd=('iptables', iptables_mac),
                error=error_msg
            ))
            iptables_failed = True
            pass
        except Exception as e:
            l.warn('{cmd}: failed: {error}'.format(
                cmd=('iptables', iptables_mac),
                error=str(e)
            ))
            error_msg = str(e)
            iptables_failed = True
            pass

    # Fallback on IP if HW address fails
    if client_ip:
        l.debug('Using client IP: {ip}'.format(
            ip=client_ip
        ))

        iptables_ip = config.get('iptables', 'iptables_ip').format(
            ip_address=client_ip
        )
        iptables_ip = tuple(iptables_ip.split(' '))

        output = BytesIO()
        error = BytesIO()
        try:
            rc = sudo.iptables(iptables_ip, _out=output, _err=error)

            if rc.exit_code == 0:
                l.debug('Created iptables IP rule successfully')
                return {
                    'error': error_msg,
                    'failed': False
                }
        except ErrorReturnCode:
            error.seek(0)
            error_msg = error.read()
            l.warn('{cmd}: exited badly: {error}'.format(
                cmd=('iptables', iptables_ip),
                error=error_msg
            ))
            iptables_failed = True
            pass
        except Exception as e:
            l.warn('{cmd}: failed: {error}'.format(
                cmd=('iptables', iptables_ip),
                error=str(e)
            ))
            error_msg = str(e)
            iptables_failed = True
            pass

    # If all else fails, error! This will be shown to end users.
    return {
        'error': error_msg,
        'failed': iptables_failed
    }


# Try to get the mac address from the IP. Requires arping installed.
def mac_from_ip(l, arping_args, ip):
    # Add IP to args
    arping_args = arping_args.format(
        ip_address=ip
    )

    # Make args into tuple
    arping_args = tuple(arping_args.split(' '))

    # Save output as buffer object
    output = BytesIO()

    # Run arping
    arping(arping_args, _out=output)
    output.seek(0)

    # Parse HW address from output
    for line in output:
        line_start = 'Unicast reply from {ip} '.format(
            ip=ip
        )
        if line.startswith(line_start):
            m = re.search('(([0-9A-Fa-f]{2}[:]){5}([0-9A-Fa-f]{2}))', line)
            if m: return m.group(0)
