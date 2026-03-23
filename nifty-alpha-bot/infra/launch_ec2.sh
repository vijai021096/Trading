#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# NIFTY Alpha Bot — EC2 Launch Script
# Provisions: Key Pair + Security Group + t3.small + Elastic IP
# Region: ap-south-1 (Mumbai) for low latency to NSE
#
# Usage:
#   chmod +x infra/launch_ec2.sh
#   ./infra/launch_ec2.sh
# ─────────────────────────────────────────────────────────────────
set -e

BOLD='\033[1m'
GREEN='\033[92m'
RED='\033[91m'
YELLOW='\033[93m'
CYAN='\033[96m'
NC='\033[0m'

REGION="ap-south-1"
KEY_NAME="nifty-bot-key"
KEY_FILE="$HOME/.ssh/${KEY_NAME}.pem"
SG_NAME="nifty-bot-sg"
INSTANCE_TYPE="t3.small"
VOLUME_SIZE=20

echo -e "${BOLD}${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${BOLD}  NIFTY Alpha Bot — EC2 Provisioning${NC}"
echo -e "${BOLD}  Region: ${REGION} (Mumbai)${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════${NC}"
echo ""

# ── Check AWS CLI is configured ───────────────────────────────────
if ! aws sts get-caller-identity --region "$REGION" &>/dev/null; then
    echo -e "${RED}ERROR: AWS CLI not configured or credentials invalid.${NC}"
    echo -e "Run: ${CYAN}aws configure${NC}"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo -e "${GREEN}✓ AWS credentials valid (Account: ${ACCOUNT_ID})${NC}"

# ── Get latest Ubuntu 22.04 LTS AMI ──────────────────────────────
echo -e "\n${YELLOW}Finding latest Ubuntu 22.04 LTS AMI...${NC}"
AMI_ID=$(aws ec2 describe-images \
    --region "$REGION" \
    --owners 099720109477 \
    --filters \
        "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
        "Name=state,Values=available" \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" \
    --output text)
echo -e "${GREEN}✓ AMI: ${AMI_ID}${NC}"

# ── Create Key Pair ───────────────────────────────────────────────
echo -e "\n${YELLOW}Creating key pair '${KEY_NAME}'...${NC}"
if aws ec2 describe-key-pairs --key-names "$KEY_NAME" --region "$REGION" &>/dev/null; then
    echo -e "${YELLOW}  Key pair already exists — skipping creation${NC}"
    if [ ! -f "$KEY_FILE" ]; then
        echo -e "${RED}  WARNING: ${KEY_FILE} not found locally. You may not be able to SSH.${NC}"
    else
        echo -e "${GREEN}  ✓ ${KEY_FILE} exists${NC}"
    fi
else
    mkdir -p "$HOME/.ssh"
    aws ec2 create-key-pair \
        --key-name "$KEY_NAME" \
        --region "$REGION" \
        --query "KeyMaterial" \
        --output text > "$KEY_FILE"
    chmod 400 "$KEY_FILE"
    echo -e "${GREEN}✓ Key saved to ${KEY_FILE}${NC}"
fi

# ── Create Security Group ─────────────────────────────────────────
echo -e "\n${YELLOW}Creating security group '${SG_NAME}'...${NC}"
MY_IP=$(curl -s https://checkip.amazonaws.com)

EXISTING_SG=$(aws ec2 describe-security-groups \
    --region "$REGION" \
    --filters "Name=group-name,Values=${SG_NAME}" \
    --query "SecurityGroups[0].GroupId" \
    --output text 2>/dev/null || echo "None")

if [ "$EXISTING_SG" != "None" ] && [ -n "$EXISTING_SG" ]; then
    SG_ID="$EXISTING_SG"
    echo -e "${YELLOW}  Security group already exists: ${SG_ID}${NC}"
else
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SG_NAME" \
        --description "NIFTY Alpha Bot - trading server" \
        --region "$REGION" \
        --query "GroupId" \
        --output text)

    # SSH — only from current IP
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp --port 22 \
        --cidr "${MY_IP}/32" \
        --region "$REGION"

    # HTTP — public (dashboard access)
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp --port 80 \
        --cidr "0.0.0.0/0" \
        --region "$REGION"

    # HTTPS — public (future SSL)
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp --port 443 \
        --cidr "0.0.0.0/0" \
        --region "$REGION"

    echo -e "${GREEN}✓ Security group created: ${SG_ID}${NC}"
    echo -e "  SSH allowed from: ${MY_IP}/32 only"
fi

# ── Launch EC2 Instance ───────────────────────────────────────────
echo -e "\n${YELLOW}Launching EC2 ${INSTANCE_TYPE} instance...${NC}"
INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":${VOLUME_SIZE},\"VolumeType\":\"gp3\"}}]" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=nifty-alpha-bot}]" \
    --query "Instances[0].InstanceId" \
    --output text)

echo -e "${GREEN}✓ Instance launched: ${INSTANCE_ID}${NC}"
echo -e "${YELLOW}  Waiting for instance to be running...${NC}"

aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
echo -e "${GREEN}✓ Instance is running${NC}"

# ── Allocate and Associate Elastic IP ────────────────────────────
echo -e "\n${YELLOW}Allocating Elastic IP (static IP for SEBI compliance)...${NC}"
ALLOC_OUTPUT=$(aws ec2 allocate-address --domain vpc --region "$REGION")
ALLOC_ID=$(echo "$ALLOC_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['AllocationId'])")
ELASTIC_IP=$(echo "$ALLOC_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['PublicIp'])")

aws ec2 associate-address \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOC_ID" \
    --region "$REGION" \
    --output text > /dev/null

echo -e "${GREEN}✓ Elastic IP allocated and associated: ${ELASTIC_IP}${NC}"

# ── Done ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  EC2 PROVISIONING COMPLETE!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  Instance ID:  ${CYAN}${INSTANCE_ID}${NC}"
echo -e "  Elastic IP:   ${CYAN}${ELASTIC_IP}${NC}"
echo -e "  SSH Key:      ${CYAN}${KEY_FILE}${NC}"
echo ""
echo -e "${BOLD}Next steps:${NC}"
echo ""
echo -e "  1. ${YELLOW}Wait ~30 seconds for SSH to be ready, then upload the project:${NC}"
echo -e "     ${CYAN}scp -i ${KEY_FILE} -r ./nifty-alpha-bot ubuntu@${ELASTIC_IP}:/opt/nifty-bot${NC}"
echo ""
echo -e "  2. ${YELLOW}SSH into the server:${NC}"
echo -e "     ${CYAN}ssh -i ${KEY_FILE} ubuntu@${ELASTIC_IP}${NC}"
echo ""
echo -e "  3. ${YELLOW}On the server, run the setup and deploy:${NC}"
echo -e "     ${CYAN}sudo bash /opt/nifty-bot/nifty-alpha-bot/infra/setup_aws.sh${NC}"
echo -e "     ${CYAN}cd /opt/nifty-bot/nifty-alpha-bot && ./deploy.sh${NC}"
echo ""
echo -e "  4. ${RED}IMPORTANT — Register this in your Kite Connect app settings:${NC}"
echo -e "     ${YELLOW}Redirect URL: http://${ELASTIC_IP}/api/kite/callback${NC}"
echo -e "     ${YELLOW}Go to: https://developers.kite.trade → Your App → Edit${NC}"
echo ""
echo -e "  5. ${YELLOW}Open the dashboard:${NC}"
echo -e "     ${CYAN}http://${ELASTIC_IP}${NC}"
echo ""

# Save details to a file for reference
cat > infra/ec2_details.txt << EOF
Instance ID:  ${INSTANCE_ID}
Elastic IP:   ${ELASTIC_IP}
SSH Key:      ${KEY_FILE}
Region:       ${REGION}
AMI:          ${AMI_ID}
Launched:     $(date)

SSH command:
  ssh -i ${KEY_FILE} ubuntu@${ELASTIC_IP}

Upload command:
  scp -i ${KEY_FILE} -r ./nifty-alpha-bot ubuntu@${ELASTIC_IP}:/opt/nifty-bot

Dashboard:
  http://${ELASTIC_IP}

Kite Redirect URL:
  http://${ELASTIC_IP}/api/kite/callback
EOF

echo -e "${GREEN}Details saved to infra/ec2_details.txt${NC}"
