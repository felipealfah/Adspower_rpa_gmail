import os
import logging
import requests
import time
import json
from credentials.credentials_manager import load_credentials, get_credential

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL base da API SMS-Activate
BASE_URL = "https://api.sms-activate.org/stubs/handler_api.php"


class SMSAPI:
    def __init__(self, api_key=None):
        # Se api_key for fornecido, use-o. Caso contrário, carregue das credenciais
        self.api_key = api_key or get_credential("SMS_ACTIVATE_API_KEY")
        self.base_url = "https://api.sms-activate.org/stubs/handler_api.php"

    def refresh_credentials(self):
        """Atualiza a chave da API carregando as credenciais mais recentes."""
        self.api_key = get_credential("SMS_ACTIVATE_API_KEY")

        if not self.api_key:
            logger.error(
                "❌ ERRO: A chave 'SMS_ACTIVATE_API_KEY' não foi encontrada em credentials.json.")
            return False
        return True

    def get_balance(self):
        """Obtém o saldo atual da conta."""
        # Sempre atualizar a chave antes de uma operação importante
        self.refresh_credentials()

        params = {'api_key': self.api_key, 'action': 'getBalance'}
        try:
            response = requests.get(BASE_URL, params=params)
            if response.status_code == 200 and 'ACCESS_BALANCE' in response.text:
                balance = float(response.text.split(':')[1])
                logger.info(f"💰 Saldo disponível: {balance} RUB")
                return balance
            else:
                logger.error(f"Erro ao obter saldo: {response.text}")
                return None
        except Exception as e:
            logger.error(f"Erro ao se conectar à API SMS: {str(e)}")
            return None

    def get_prices(self, service=None, countries=None):
        """
        Obtém preços dos números de telefone por país e serviço.

        Args:
            service (str, optional): Código do serviço (ex: "go" para Gmail).
            countries (list, optional): Lista de códigos de países para filtrar.

        Returns:
            dict: Dicionário estruturado com preços e quantidades disponíveis.
        """
        # Sempre atualizar a chave
        self.refresh_credentials()

        # Validar o parâmetro countries
        if countries is not None and not isinstance(countries, (list, tuple, set)):
            logger.warning(
                f"⚠️ Parâmetro 'countries' inválido: {type(countries)}. Deve ser lista ou tupla.")
            countries = []

        params = {'api_key': self.api_key, 'action': 'getPrices'}

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)

            if response.status_code != 200:
                logger.error(f"Erro ao obter preços: {response.text}")
                return {}

            data = response.json()
            prices = {}

            # Processar todos os países da resposta
            for country, services in data.items():
                # Filtrar apenas os países especificados (se fornecido)
                if countries and country not in countries:
                    continue

                for srv, details in services.items():
                    if service is None or srv == service:  # Filtra pelo serviço se especificado
                        prices.setdefault(country, {})[srv] = {
                            "cost": float(details["cost"]),
                            "count": int(details["count"])
                        }

            return prices
        except Exception as e:
            logger.error(f"Erro ao obter preços: {str(e)}")
            return {}  # Retornar dicionário vazio em vez de None

    def get_number_status(self, country, service):
        """Verifica disponibilidade de números para um serviço em um país específico."""
        # Atualizar credenciais
        self.refresh_credentials()

        if not country or not service:
            logger.warning(
                "⚠️ País ou serviço não fornecido para verificação de status")
            return 0

        params = {
            'api_key': self.api_key,
            'action': 'getNumbersStatus',
            'country': country
        }

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Validar o formato do retorno
                if not isinstance(data, dict):
                    logger.warning(f"⚠️ Resposta de API inesperada: {data}")
                    return 0

                # Retorna a quantidade disponível para o serviço específico
                service_count = data.get(service, 0)
                return int(service_count) if service_count is not None else 0
            else:
                logger.error(
                    f"Erro ao verificar disponibilidade: {response.text}")
                return 0
        except Exception as e:
            logger.error(f"❌ Erro ao verificar status dos números: {str(e)}")
            return 0

    def get_sms_code(self, activation_id, max_attempts=10, interval=10):
        """Verifica se o SMS foi recebido e retorna o código."""
        # Atualizar credenciais
        self.refresh_credentials()

        params = {'api_key': self.api_key,
                  'action': 'getStatus', 'id': activation_id}
        logger.info(f"📩 Aguardando SMS para ID {activation_id}...")

        for attempt in range(max_attempts):
            try:
                response = requests.get(BASE_URL, params=params, timeout=15)
                if response.status_code == 200:
                    if 'STATUS_OK' in response.text:
                        _, code = response.text.split(':')
                        logger.info(f"✅ Código recebido: {code}")
                        # Confirmação de código recebido
                        self.set_status(activation_id, 3)
                        return code
                    elif 'STATUS_CANCEL' in response.text:
                        logger.warning("🚨 Ativação cancelada pelo sistema.")
                        return None
                else:
                    logger.error(f"Erro ao verificar SMS: {response.text}")
            except Exception as e:
                logger.error(f"Erro ao verificar código SMS: {str(e)}")

            time.sleep(interval)

        logger.warning("⏳ Tempo esgotado, nenhum SMS recebido.")
        self.set_status(activation_id, 6)  # Cancelar ativação
        return None

    def set_status(self, activation_id, status):
        """
        Define o status da ativação:
            1 = Número recebido e aguardando SMS
            3 = Código SMS recebido e inserido
            6 = Cancelar número (caso não seja mais necessário)
            8 = Número confirmado com sucesso
        """
        # Atualizar credenciais
        self.refresh_credentials()

        params = {
            "api_key": self.api_key,
            "action": "setStatus",
            "id": activation_id,
            "status": status
        }

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)

            if response.status_code == 200:
                if "ACCESS_CANCEL" in response.text:
                    logger.info(
                        f"✅ Número {activation_id} cancelado com sucesso.")
                    return True
                elif "NO_ACTIVATION" in response.text:
                    logger.warning(
                        f"⚠️ Não foi possível cancelar o número {activation_id}. Ele pode já estar expirado ou inválido.")
                else:
                    logger.error(
                        f"❌ Erro ao cancelar o número {activation_id}: {response.text}")
            else:
                logger.error(
                    f"❌ Erro de conexão ao tentar cancelar o número {activation_id}: {response.status_code}")
        except Exception as e:
            logger.error(f"Erro ao definir status da ativação: {str(e)}")

        return False  # Retorna False caso a operação não tenha sido bem-sucedida

    def reuse_number_for_service(self, activation_id, new_service):
        """
        Tenta reutilizar um número para um serviço diferente.

        Args:
            activation_id (str): ID da ativação original.
            new_service (str): Código do novo serviço (ex: "tk" para TikTok).

        Returns:
            bool: True se a reutilização for bem-sucedida, False caso contrário.
        """
        # Atualizar credenciais
        self.refresh_credentials()

        params = {
            "api_key": self.api_key,
            "action": "getExtraService",
            "id": activation_id,
            "service": new_service
        }

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)
            if "ACCESS_EXTRA_SERVICE" in response.text:
                logger.info(
                    f"✅ Número reutilizado com sucesso para {new_service} (ID: {activation_id})")
                return True
            else:
                logger.warning(
                    f"❌ Falha ao reutilizar número para {new_service}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Erro ao reutilizar número: {str(e)}")
            return False

    def get_number(self, service, country):
        """
        Obtém um número de telefone de um país específico.

        Args:
            service (str): Código do serviço (ex: "go" para Gmail)
            country (str): Código do país

        Returns:
            tuple: (activation_id, phone_number) ou (None, None) em caso de falha
        """
        # Atualizar credenciais
        self.refresh_credentials()

        params = {
            'api_key': self.api_key,
            'action': 'getNumber',
            'service': service,
            'country': country
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=15)
            response_text = response.text

            if "ACCESS_NUMBER" in response_text:
                _, activation_id, phone_number = response_text.split(":")
                return activation_id.strip(), phone_number.strip()
            else:
                # Tratar erros específicos
                error_messages = {
                    "NO_NUMBERS": "Sem números disponíveis",
                    "NO_BALANCE": "Saldo insuficiente",
                    "BAD_SERVICE": "Serviço inválido",
                    "BAD_KEY": "Chave de API inválida"
                }

                for error_code, message in error_messages.items():
                    if error_code in response_text:
                        logger.error(
                            f"❌ {message} para {service} no país {country}")
                        return None, None

                logger.error(f"❌ Erro desconhecido: {response_text}")
                return None, None

        except Exception as e:
            logger.error(f"❌ Erro ao obter número: {str(e)}")
            return None, None

    def cancel_number(self, activation_id):
        """
        Cancela um número na API SMS-Activate.

        Args:
            activation_id (str): O ID do número a ser cancelado.

        Returns:
            bool: True se o cancelamento foi bem-sucedido, False caso contrário.
        """
        # Atualizar credenciais
        self.refresh_credentials()

        params = {
            "api_key": self.api_key,  # Usar a chave de API carregada
            "action": "cancel",
            "id": activation_id
        }

        try:
            response = requests.get(BASE_URL, params=params, timeout=10)
            response_data = response.text

            if "ACCESS_CANCEL" in response_data:
                logger.info(f"Número {activation_id} cancelado com sucesso.")
                return True
            else:
                logger.error(
                    f"Erro ao cancelar número {activation_id}: {response_data}")
                return False
        except Exception as e:
            logger.error(
                f"Erro ao fazer requisição para cancelar número: {str(e)}")
            return False  # Retorna a resposta da API para o PhoneManager processar
