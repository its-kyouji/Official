client
dev tun
proto tcp
remote SERVER_IP_PLACEHOLDER 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
verb 3
<ca>
INSERT_CA_CERTIFICATE_HERE
</ca>
<cert>
INSERT_CLIENT_CERTIFICATE_HERE
</cert>
<key>
INSERT_CLIENT_KEY_HERE
</key>
