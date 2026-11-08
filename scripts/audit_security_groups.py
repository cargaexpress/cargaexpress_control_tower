import subprocess
import json

sgs = json.loads(subprocess.check_output([
    'aws', 'ec2', 'describe-security-groups',
    '--filters', 'Name=vpc-id,Values=vpc-0ab8c56e522b2034f',
    '--region', 'us-east-2'
], text=True))['SecurityGroups']

print(f"Total Security Groups in VPC: {len(sgs)}\n")

for sg in sorted(sgs, key=lambda x: x['GroupName']):
    print("=" * 70)
    print(f"Security Group: {sg['GroupName']}")
    print(f"ID:             {sg['GroupId']}")
    print(f"Description:    {sg['Description']}")
    print("-" * 70)
    print("INGRESS (Tráfico Entrante):")
    if not sg.get('IpPermissions'):
        print("  (Ninguna regla de entrada - Bloqueo total)")
    for rule in sg.get('IpPermissions', []):
        proto = rule.get('IpProtocol')
        from_port = rule.get('FromPort')
        to_port = rule.get('ToPort')
        port_str = f"{from_port}-{to_port}" if from_port is not None else "ALL"
        if from_port == to_port and from_port is not None:
            port_str = str(from_port)
            
        sources = [f"CIDR: {r['CidrIp']}" for r in rule.get('IpRanges', [])]
        sources += [f"SG: {g['GroupId']}" for g in rule.get('UserIdGroupPairs', [])]
        print(f"  * Protocolo {proto} | Puerto {port_str:10} | Desde: {', '.join(sources)}")
        
    print("\nEGRESS (Tráfico Saliente):")
    for rule in sg.get('IpPermissionsEgress', []):
        proto = rule.get('IpProtocol')
        from_port = rule.get('FromPort')
        to_port = rule.get('ToPort')
        port_str = f"{from_port}-{to_port}" if from_port is not None else "ALL"
        if from_port == to_port and from_port is not None:
            port_str = str(from_port)
            
        dest = [f"CIDR: {r['CidrIp']}" for r in rule.get('IpRanges', [])]
        dest += [f"SG: {g['GroupId']}" for g in rule.get('UserIdGroupPairs', [])]
        print(f"  * Protocolo {proto} | Puerto {port_str:10} | Hacia: {', '.join(dest)}")
    print()
