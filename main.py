import requests
import time
import smtplib
import yaml
from email.mime.text import MIMEText
from datetime import datetime
import logging
from typing import Dict, List, Optional, Tuple
import re

class NodeExporterMonitor:
    def __init__(self, config_path: str):
        self.load_config(config_path)
        self.setup_logging()

    def load_config(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

    def setup_logging(self) -> None:
        """Configure logging."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config['logging']['file']),
                logging.StreamHandler()
            ]
        )

    def parse_metric_line(self, line: str) -> Optional[Tuple[str, float, Dict[str, str]]]:
        """Parse a single metric line in Prometheus format."""
        if line.startswith('#') or not line.strip():
            return None

        # Split metric name and labels from value
        try:
            name_part, value_str = line.split(' ')

            # Parse labels if they exist
            labels = {}
            if '{' in name_part:
                metric_name = name_part[:name_part.index('{')]
                labels_str = name_part[name_part.index('{') + 1:name_part.rindex('}')]

                # Parse individual labels
                for label_pair in re.findall(r'(\w+)="([^"]*)"', labels_str):
                    labels[label_pair[0]] = label_pair[1]
            else:
                metric_name = name_part

            return metric_name, float(value_str), labels
        except Exception:
            return None

    def fetch_metrics(self) -> List[Tuple[str, float, Dict[str, str]]]:
        """Fetch and parse metrics from node exporter."""
        try:
            response = requests.get(f"http://{self.config['node_exporter']['host']}:{self.config['node_exporter']['port']}/metrics")
            response.raise_for_status()

            metrics = []
            for line in response.text.split('\n'):
                parsed = self.parse_metric_line(line)
                if parsed:
                    metrics.append(parsed)

            return metrics
        except Exception as e:
            logging.error(f"Failed to fetch metrics: {str(e)}")
            return []

    def send_email(self, subject: str, body: str) -> None:
        """Send email alert."""
        try:
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.config['email']['from']
            msg['To'] = self.config['email']['to']

            with smtplib.SMTP(self.config['email']['smtp_server'], self.config['email']['smtp_port']) as server:
                if self.config['email'].get('use_tls', True):
                    server.starttls()
                if 'username' in self.config['email']:
                    server.login(self.config['email']['username'], self.config['email']['password'])
                server.send_message(msg)

            logging.info(f"Alert email sent: {subject}")
        except Exception as e:
            logging.error(f"Failed to send email: {str(e)}")

    def evaluate_metric_rule(self, metric_name: str, value: float, labels: Dict[str, str], rule: Dict) -> Optional[str]:
        """Evaluate a single metric against its rule."""
        if rule.get('label_match'):
            for label, pattern in rule['label_match'].items():
                if label not in labels or not re.match(pattern, labels[label]):
                    return None

        if rule.get('gt') and value > rule['gt']:
            return f"{metric_name} is {value}, which is greater than {rule['gt']}"
        if rule.get('lt') and value < rule['lt']:
            return f"{metric_name} is {value}, which is less than {rule['lt']}"
        if rule.get('eq') and value == rule['eq']:
            return f"{metric_name} is {value}, which equals {rule['eq']}"

        return None

    def check_metrics(self) -> None:
        """Check metrics against rules and send alerts if needed."""
        metrics = self.fetch_metrics()
        alerts = []

        for metric_name, value, labels in metrics:
            # Check if we have rules for this metric
            if metric_name in self.config['rules']:
                rule = self.config['rules'][metric_name]
                alert_message = self.evaluate_metric_rule(metric_name, value, labels, rule)
                if alert_message:
                    alerts.append(alert_message)

        if alerts:
            subject = f"Node Exporter Alert - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            body = "The following issues were detected:\n\n" + "\n".join(alerts)
            self.send_email(subject, body)

        logging.info(f"Check completed - Found {len(alerts)} alerts")

    def start(self) -> None:
        """Start the monitoring loop."""
        logging.info("Starting node exporter monitoring system...")

        while True:
            try:
                self.check_metrics()
                time.sleep(self.config['check_interval'])
            except KeyboardInterrupt:
                logging.info("Monitoring stopped by user")
                break
            except Exception as e:
                logging.error(f"Error in monitoring loop: {str(e)}")
                time.sleep(60)  # Wait a minute before retrying

if __name__ == "__main__":
    monitor = NodeExporterMonitor('config.yml')
    monitor.start()
