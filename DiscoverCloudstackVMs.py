#!/usr/bin/env python3
import pynetbox
import yaml
import datetime
import ipaddress
from cs import CloudStack


def ctime():
    return str(datetime.datetime.now())


def cs2netbox_vm_status(cs_state):
    status_dict = {'Running': 1}
    return status_dict.get(cs_state,0)


if __name__ == "__main__":
    config_file_name = 'config.yml'
    cs_domain_id = '45c086dc-4beb-11e5-a929-de020e22981e'
    cluster_name = 'CloudStack'
    cluster_id = 1
    vm_role_name = 'Common Purpose VM'
    vm_role_id =  4
    try:
        with open(config_file_name) as config_file:
            cfg = yaml.load(config_file.read())
    except FileNotFoundError or FileExistsError as Error:
        print('Can not open configuration file {}'.format(config_file_name))
        print(Error)
        exit(-1)
    except yaml.scanner.ScannerError as Error:
        print('Error while parsing configuration file {}'.format(config_file_name))
        print(Error)
        exit(-1)
    except Exception as Error:
        print(Error)
        exit(-1)
    try:
        nb = pynetbox.api(**cfg['netbox'])
    except KeyError as Error:
        print('Netbox configuration not found.')
        exit(-1)
    except Exception as Error:
        print('PyNetbox: ', Error)
        exit(-1)
    try:
        dvb_cs = CloudStack(**cfg['cloudstack'])
    except KeyError as Error:
        print('Cloudstack configuration not found.')
        exit(-1)
    except Exception as Error:
        print('Cloudstack: ', Error)
        exit(-1)

    netbox_vms = nb.virtualization.virtual_machines.filter(cluster_name=cluster_name)
# Getting platforms from netbox and making dictionary with slugs as a key
    platforms_dict = dict(map(lambda nb_pl: (nb_pl.slug, nb_pl.id), nb.dcim.platforms.all()))
# Getting diskofferings from Cloudstack and making dictionary with id and space amount
    # do_dict = dict(map(lambda cs_do: (cs_do['id'], cs_do['disksize']), dvb_cs.listDiskOfferings()['diskoffering']))
    cs_vms = dvb_cs.listVirtualMachines(domainid=cs_domain_id)['virtualmachine']
# Checking if VM in Netbox is exist in CloudStack. If not, then deleting VM in Netbox
    netbox_vm_deleted = False
    for netbox_vm in netbox_vms:
        netbox_vm_exist = False
        for cs_vm in cs_vms:
            if netbox_vm.custom_fields['vmid'] == cs_vm['id']:
                netbox_vm_exist = True
                break
        if not netbox_vm_exist:
            print('{} Virtual machine name={} id={} not found in {}. Deleting from netbox'.
                  format(ctime(), netbox_vm.name, netbox_vm.custom_fields['vmid'], cluster_name))
            if not netbox_vm.delete():
                print('{} Can not delete from netbox virtual machine name={} id={}'.
                      format(ctime(), netbox_vm.name, netbox_vm.custom_fields['vmid']))
            else:
                netbox_vm_deleted = True
    if netbox_vm_deleted:
        netbox_vms = nb.virtualization.virtual_machines.filter(cluster_name=cluster_name)
    netbox_vmid_set = set()
# Creating a set of netbox VM IDs for further check if VM from Cloudstack already exists in netbox
    for netbox_vm in netbox_vms:
        netbox_vmid_set.add(netbox_vm.custom_fields['vmid'])
    vms_added = 0
    for cs_vm in cs_vms:
        if cs_vm['id'] in netbox_vmid_set:
            print('{} Found in netbox virtual machine name={} id={}'.
                  format(ctime(), cs_vm['name'], cs_vm['id']))
        else:
            print('{} Creating in netbox virtual machine name={} id={}'.
                  format(ctime(), cs_vm['name'], cs_vm['id']))
            nb_vm_args = {'name': cs_vm['name'],
                          'role': vm_role_id,
                          'cluster': cluster_id,
                          'platform': platforms_dict[cs_vm['guestosid']],
                          'vcpus': cs_vm['cpunumber'],
                          'memory': cs_vm['memory'],
                          'status': cs2netbox_vm_status(cs_vm['state']),
                          'custom_fields': {'vmid': cs_vm['id'],
                                            'account': cs_vm['account'],
                                            'hostname': cs_vm.get('hostname',None),
                                            'templatename': cs_vm['templatename'],
                                            'hypervisor': cs_vm['hypervisor'],
                                            'created': cs_vm['created'].replace('T', ' ')[:10]}
                          }
            nb_new_vm = None
            try:
                nb_new_vm = nb.virtualization.virtual_machines.create(**nb_vm_args)
                if not nb_new_vm:
                    print('{} Error while Creating in netbox virtual machine name={} id={} nb_vm_args={}'.
                          format(ctime(), cs_vm['name'], cs_vm['id'], nb_vm_args))
            except pynetbox.RequestError as Error:
                print('{} Exception "{}" while Creating in netbox virtual machine name={} id={} nb_vm_args={}'.
                      format(ctime(), Error,cs_vm['name'], cs_vm['id'], nb_vm_args))
            # print(nb_new_vm)
            if nb_new_vm:
                no_primary_ip = True
                for i in range(len(cs_vm['nic'])):
                    this_nic = cs_vm['nic'][i]
                    nb_int_args = {'virtual_machine': nb_new_vm['id'],
                                   'name': 'eth{}'.format(i),
                                   'mac_address': this_nic['macaddress'],
                                   'form_factor': 0
                                   }
                    # print(nb_int_args)
                    nb_new_int = None
                    try:
                        nb_new_int = nb.virtualization.interfaces.create(**nb_int_args)
                        # print(nb_new_int)
                        if nb_new_int:
                            nb_ip_args = {'status': 1,
                                          'address': str(ipaddress.ip_interface('{}/{}'.format(this_nic['ipaddress'],
                                                                                               this_nic['netmask'])))
                                          }
                            # print(nb_ip_args)
                            nb_new_ip = None
                            nb_new_ip = nb.ipam.ip_addresses.create(**nb_ip_args)
                            if nb_new_ip:
                                #nb_update_interface = nb.virtualization.interfaces.get(nb_new_int['id'])
                                nb_update_ip = nb.ipam.ip_addresses.get(nb_new_ip['id'])
                                nb_update_ip.interface = nb_new_int['id']
                                if nb_update_ip.save() and no_primary_ip:
                                    nb_update_vm = nb.virtualization.virtual_machines.get(nb_new_vm['id'])
                                    nb_update_vm.primary_ip4 = nb_update_ip
                                    nb_update_vm.primary_ip = nb_update_ip
                                    nb_update_vm.save()
                                    no_primary_ip = False
                    except pynetbox.RequestError as Error:
                        print('{} Exception "{}" while Creating  netbox VM interface  name={} nic={}'.
                              format(ctime(), Error, cs_vm['name'], this_nic))
            vms_added += 1
            #exit(0)
    print('{} All {} VMs added successfully'.format(ctime(), vms_added))
