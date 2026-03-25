# HDD Prep Command Center v5.0

Professional HDD inspection, wiping, and grading station for Ubuntu Server.

### Features
- **Dual Mode:** Full Prep (NIST Wipe) or Verify Only (Quick SMART Check).
- **Auto-Grading:** Assigns Grade A/B/C based on hours and bad sectors.
- **Identity Fix:** Manually assign serials if USB bridges hide them.
- **Certification:** Generates text-based erasure certificates.

### Installation
```bash
git clone [https://github.com/YOUR_USERNAME/hdd-prep-station.git](https://github.com/YOUR_USERNAME/hdd-prep-station.git)
cd hdd-prep-station
chmod +x setup.sh
./setup.sh
source ~/.bashrc
