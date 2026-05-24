# Network topology

## Subnet
- 192.168.1.0/24
- Router: 192.168.1.1

## Static IP plan
| Range | Purpose |
|---|---|
| .10–.19 | Infrastructure |
| .20–.49 | optibox harness Pis |
| .100–.199 | Cluster nodes |
| .200–.249 | Sub-clusters/testbeds |

## Naming
- `node-NN` (NN = static IP last octet)
- Aliases in /etc/hosts: p100a, p100b, 1060a, head

## Ports
| Port | Service |
|---|---|
| 22 | SSH |
| 8080 | OpenAI API (headd) |
| 9090 | Prometheus /metrics |
| 11000 | Ring transport (ZMQ PULL) |
| 11001 | Ring control (ZMQ ROUTER) |
| 11002 | Heartbeat (UDP) |
| 11003 | Discovery (UDP multicast) |
| 8765 | optibox MCP (on Pi) |

## Multicast
- Discovery: 239.42.42.42:11003, TTL=1

## Jumbo frames
- MTU 9000 everywhere on cluster subnet
- Verify: `ping -M do -s 8972 <peer>`

## 10 GbE direct
- p100a:eth1 ↔ p100b:eth1 via DAC, no switch
- /30 subnet 192.168.99.0/30 for RDMA
- in-kernel mlx4 driver (ConnectX-3)
