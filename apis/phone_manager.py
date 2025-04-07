import json
import os
import time
import logging
from datetime import datetime, timedelta
import requests
from apis.sms_api import SMSAPI

logger = logging.getLogger(__name__)


class PhoneManager:
    """
    Gerencia números de telefone, permitindo reutilização de números recentes.
    Otimiza uso de créditos do serviço SMS guardando números que ainda podem ser usados.
    """

    def __init__(self, storage_path="credentials/phone_numbers.json"):
        """
        Inicializa o gerenciador de números de telefone.

        Args:
            storage_path: Caminho para o arquivo JSON de armazenamento
        """
        self.storage_path = storage_path
        self.numbers = self._load_numbers()
        self.reuse_window = 30 * 60  # 30 minutos em segundos - janela de reutilização
        self.api_key = self.load_api_key()

        # Instanciar a API SMS
        self.sms_api = SMSAPI(self.api_key)

        # Definição dos países e suas prioridades
        self.selected_countries = {
            # Brasil como primeira opção (prioridade absoluta)
            "73": "Brasil",
            "36": "Canadá",     # Canadá
            "187": "Estados Unidos",  # Estados Unidos
            "52": "México",     # México
            "16": "Reino Unido",  # Reino Unido
            "151": "Chile",     # Chile
            "224": "Paraguai",  # Paraguai
            "156": "Peru",      # Peru
            "225": "Uruguai"    # Uruguai
        }

        # Ordem de prioridade para busca de países
        self.country_priority = ["73", "187", "36",
                                 "52", "16", "151", "224", "156", "225"]

    def _load_numbers(self):
        """Carrega os números do arquivo de armazenamento."""
        if not os.path.exists(self.storage_path):
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            return []

        try:
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_numbers(self):
        """Salva os números no arquivo de armazenamento."""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, 'w') as f:
            json.dump(self.numbers, f, indent=4)

    def add_number(self, phone_number, country_code, activation_id, service="go"):
        """
        Adiciona ou atualiza um número no gerenciador.
        """
        if not all([phone_number, country_code, activation_id]):
            logger.error("❌ Dados de telefone incompletos, não será salvo")
            return False

        current_time = time.time()

        # Verificar se o número já existe
        for number in self.numbers:
            if number["phone_number"] == phone_number:
                # Atualizar dados existentes
                number["last_used"] = current_time
                number["times_used"] += 1
                if service not in number["services"]:
                    number["services"].append(service)
                self._save_numbers()
                logger.info(
                    f"✅ Número {phone_number} atualizado no gerenciador")
                return True

        # Adicionar novo número
        new_number = {
            "phone_number": phone_number,
            "country_code": country_code,
            "activation_id": activation_id,
            "first_used": current_time,
            "last_used": current_time,
            "services": [service],
            "times_used": 1
        }

        self.numbers.append(new_number)
        self._save_numbers()
        logger.info(f"✅ Número {phone_number} adicionado ao gerenciador")
        return True

    def get_reusable_number(self, service="go"):
        """
        Obtém um número reutilizável que ainda está dentro da janela de validade,
        priorizando números brasileiros.

        Args:
            service: Código do serviço para o qual o número será usado

        Returns:
            dict: Informações do número reutilizável ou None se não houver
        """
        current_time = time.time()

        # Primeiro tentar encontrar números brasileiros
        brazilian_numbers = []
        other_numbers = {
            "151": [],  # Chile
            "224": [],  # Paraguai
            "156": [],  # Peru
            "225": []  # Uruguai
        }

        # Limpar números expirados
        self._cleanup_expired_numbers()

        # Primeiro separar números brasileiros dos demais
        for number in self.numbers:
            time_since_last_use = current_time - number["last_used"]

            # Verificar se está dentro da janela de reutilização
            if time_since_last_use < self.reuse_window:
                # Verificar se o número não foi usado para este serviço
                if service not in number["services"]:
                    country_code = number["country_code"]
                    if country_code == "73":  # Brasil
                        brazilian_numbers.append(number)
                    elif country_code in other_numbers:
                        other_numbers[country_code].append(number)

        # Primeiro tentar usar números brasileiros
        if brazilian_numbers:
            # Ordenar por menos utilizado primeiro
            brazilian_numbers.sort(key=lambda x: x["times_used"])
            selected = brazilian_numbers[0]
            selected["last_used"] = current_time
            selected["times_used"] += 1
            selected["services"].append(service)
            self._save_numbers()

            time_left = self.reuse_window - \
                (current_time - selected["first_used"])
            minutes_left = int(time_left / 60)
            logger.info(
                f"✅ Reutilizando número brasileiro {selected['phone_number']} ({minutes_left} minutos restantes)")
            return selected

        # Se não houver números brasileiros, tentar outros países na ordem de prioridade
        # Chile, Paraguai, Peru, Uruguai
        priority_order = ["151", "224", "156", "225"]
        for country_code in priority_order:
            country_numbers = other_numbers[country_code]
            if country_numbers:
                # Ordenar por menos utilizado primeiro
                country_numbers.sort(key=lambda x: x["times_used"])
                selected = country_numbers[0]
                selected["last_used"] = current_time
                selected["times_used"] += 1
                selected["services"].append(service)
                self._save_numbers()

                time_left = self.reuse_window - \
                    (current_time - selected["first_used"])
                minutes_left = int(time_left / 60)
                country_name = self.get_country_name(country_code)
                logger.warning(
                    f"⚠️ Reutilizando número de {country_name} pois não há números brasileiros disponíveis. {selected['phone_number']} ({minutes_left} minutos restantes)")
                return selected

        logger.warning("❌ Nenhum número disponível para reutilização")
        return None

    def get_country_name(self, country_code):
        """Retorna o nome do país baseado no código."""
        country_names = {
            "73": "Brasil",
            "36": "Canadá",
            "187": "Estados Unidos",
            "52": "México",
            "16": "Reino Unido",
            "151": "Chile",
            "224": "Paraguai",
            "156": "Peru",
            "225": "Uruguai"
        }
        return country_names.get(country_code, "Desconhecido")

    def _cleanup_expired_numbers(self):
        """Remove números que já expiraram da janela de reutilização."""
        current_time = time.time()
        self.numbers = [
            number for number in self.numbers
            if (current_time - number["first_used"]) < self.reuse_window
        ]
        self._save_numbers()

    def mark_number_used(self, phone_number, service="go"):
        """
        Marca um número como usado para um determinado serviço.

        Args:
            phone_number: Número de telefone
            service: Código do serviço
        """
        for number in self.numbers:
            if number["phone_number"] == phone_number:
                number["last_used"] = time.time()
                number["times_used"] += 1
                if service not in number["services"]:
                    number["services"].append(service)
                self._save_numbers()
                return True
        return False

    def get_stats(self):
        """
        Retorna estatísticas sobre os números gerenciados.

        Returns:
            dict: Estatísticas de uso dos números
        """
        total_numbers = len(self.numbers)
        total_uses = sum(number.get("times_used", 0)
                         for number in self.numbers)
        active_numbers = sum(
            1 for number in self.numbers if number.get("is_active", False))

        # Contar serviços utilizados
        total_services = sum(len(number.get("services", []))
                             for number in self.numbers)

        return {
            "total_numbers": total_numbers,
            "total_uses": total_uses,
            "active_numbers": active_numbers,
            "total_services": total_services,
            "estimated_savings": self.calculate_estimated_savings()
        }

    def calculate_estimated_savings(self):
        """Calcula a economia estimada com base no uso dos números."""
        total_savings = 0
        for number in self.numbers:
            # Supondo que você tenha um campo 'savings_per_use' em cada número
            savings_per_use = number.get("savings_per_use", 0)
            times_used = number.get("times_used", 0)
            total_savings += savings_per_use * times_used
        return total_savings

    def load_api_key(self):
        """Carrega a chave da API do arquivo de credenciais."""
        try:
            with open("credentials/credentials.json", "r") as file:
                credentials = json.load(file)
                api_key = credentials.get("SMS_ACTIVATE_API_KEY", None)

                if not api_key:
                    logger.error(
                        "❌ Chave da API não encontrada no arquivo de credenciais")

                return api_key
        except Exception as e:
            logger.error(f"❌ Erro ao carregar a chave da API: {str(e)}")
            return None

    def cancel_number(self, activation_id):
        """
        Cancela um número na API e o remove do gerenciador.
        """
        # Delegar o cancelamento para a API SMS
        result = self.sms_api.cancel_number(activation_id)

        # Se cancelado com sucesso, remover do gerenciador
        if result:
            for i, number in enumerate(self.numbers):
                if number["activation_id"] == activation_id:
                    del self.numbers[i]  # Remove o número da lista
                    self._save_numbers()  # Salva as alterações
                    logger.info(
                        f"Número com ID {activation_id} removido do gerenciador")
                    break

        return result

    def remove_number(self, phone_number):
        """
        Remove um número do gerenciador.

        Args:
            phone_number (str): O número de telefone a ser removido.

        Returns:
            bool: True se a remoção foi bem-sucedida, False caso contrário.
        """
        for i, number in enumerate(self.numbers):
            if number["phone_number"] == phone_number:
                del self.numbers[i]  # Remove o número da lista
                self._save_numbers()  # Salva as alterações no arquivo
                logger.info(f"✅ Número {phone_number} removido com sucesso.")
                return True
        logger.warning(f"⚠️ Número {phone_number} não encontrado.")
        return False

    def buy_number_with_retry(self, service, country, max_brazil_attempts=5):
        """
        Tenta obter um número brasileiro com até 5 tentativas antes de usar outro país.

        Args:
            service: Código do serviço (ex: "go" para Gmail)
            country: Código do país alternativo caso Brasil não esteja disponível
            max_brazil_attempts: Número máximo de tentativas para obter número brasileiro

        Returns:
            tuple: (activation_id, phone_number) ou (None, None) em caso de falha
        """
        brazil_code = "73"

        # Apenas forçar Brasil para Gmail
        if service == "go":
            logger.info(
                f"🔄 Tentando obter número brasileiro para {service} (máx: {max_brazil_attempts} tentativas)")

            for attempt in range(max_brazil_attempts):
                try:
                    # Verificar disponibilidade - com retry
                    def check_brazil():
                        try:
                            return self.get_number_status(brazil_code, service)
                        except Exception as inner_e:
                            logger.error(
                                f"❌ Erro ao verificar disponibilidade: {str(inner_e)}")
                            return 0

                    brazil_available = self.execute_with_retry(check_brazil)

                    if brazil_available is None or brazil_available <= 0:
                        logger.warning(
                            f"⚠️ Tentativa {attempt+1}/{max_brazil_attempts}: Sem números brasileiros disponíveis")
                        time.sleep(2)
                        continue

                    logger.info(
                        f"🇧🇷 Tentativa {attempt+1}/{max_brazil_attempts}: {brazil_available} números brasileiros disponíveis")

                    # Tentar comprar o número - com retry
                    def buy_brazilian():
                        try:
                            result = self.sms_api.get_number(
                                service, brazil_code)

                            # Validar resultado
                            if isinstance(result, tuple) and len(result) == 2:
                                activation_id, phone_number = result
                                # Garantir que são strings válidas
                                activation_id = str(
                                    activation_id) if activation_id else None
                                phone_number = str(
                                    phone_number) if phone_number else None
                                return activation_id, phone_number

                            logger.warning(
                                f"⚠️ Formato inesperado do resultado: {result}")
                            return None, None
                        except Exception as inner_e:
                            logger.error(
                                f"❌ Erro ao comprar número: {str(inner_e)}")
                            return None, None

                    activation_id, phone_number = self.execute_with_retry(
                        buy_brazilian)

                    # Validar resultados
                    if activation_id and phone_number:
                        logger.info(
                            f"✅ Número brasileiro obtido com sucesso na tentativa {attempt+1}")
                        try:
                            # Adicionar ao gerenciador
                            self.add_number(phone_number, brazil_code,
                                            activation_id, service)
                            return activation_id, phone_number
                        except Exception as e:
                            logger.error(
                                f"❌ Erro ao adicionar número ao gerenciador: {str(e)}")
                            return activation_id, phone_number
                    else:
                        logger.warning(
                            f"⚠️ Falha na tentativa {attempt+1} de obter número brasileiro")

                    time.sleep(2)
                except Exception as e:
                    logger.error(f"❌ Erro na tentativa {attempt+1}: {str(e)}")
                    time.sleep(2)

            logger.warning(
                f"❌ Falha após {max_brazil_attempts} tentativas de obter número brasileiro")

        # Se chegou aqui, usar país alternativo
        logger.info(f"🔄 Tentando país alternativo: {country}")
        return self.buy_number(service, country)

    def compare_prices_in_selected_countries(self, service):
        """
        Compara os preços e disponibilidade de um serviço entre os países selecionados.

        Args:
            service (str): Código do serviço para verificar (ex: "go" para Gmail).

        Returns:
            list: Lista ordenada de dicionários com informações de cada país.
        """
        try:
            # Utilizar o método get_prices já implementado
            filtered_prices = self.get_prices(service)

            if not filtered_prices:
                logger.error(
                    f"❌ Não foi possível obter os preços para o serviço {service}")
                return []

            logger.info(f"📊 Analisando preços para o serviço {service}")
            service_prices = []

            # Processar os dados de preços para cada país
            for country_code, services in filtered_prices.items():
                if service in services:
                    try:
                        country_name = self.selected_countries.get(
                            country_code, "Desconhecido")
                        price_info = services[service]

                        # Verificar disponibilidade atual (preço pode estar desatualizado) - com retry
                        def check_availability():
                            return self.get_number_status(country_code, service)

                        available_count = self.execute_with_retry(
                            check_availability)

                        if available_count is None:
                            available_count = 0

                        price_rub = float(price_info["cost"])

                        service_prices.append({
                            'country_code': country_code,
                            'country_name': country_name,
                            'price': price_rub,
                            'available': available_count
                        })

                        logger.info(
                            f"💰 {country_name}: {price_rub} RUB ({available_count} disponíveis)")

                    except (ValueError, KeyError) as e:
                        logger.warning(
                            f"⚠️ Erro ao processar preços para {country_code}: {str(e)}")

            # Ordenar do mais barato para o mais caro
            sorted_prices = sorted(service_prices, key=lambda x: x['price'])

            if not sorted_prices:
                logger.warning(
                    f"⚠️ Nenhum número disponível para {service} nos países selecionados")

            return sorted_prices

        except Exception as e:
            logger.error(f"❌ Erro ao comparar preços: {str(e)}")
            return []

    def get_cheapest_country(self, service):
        """
        Encontra o país mais adequado para um serviço, priorizando Brasil primeiro.
        Ordem de prioridade:
        1. Brasil (73)
        2. Canadá (36)
        3. Estados Unidos (187)
        4. México (52)
        5. Reino Unido (16)
        6. Chile (151)
        7. Paraguai (224)
        8. Peru (156)
        9. Uruguai (225)
        """
        # Brasil SEMPRE deve ser a prioridade absoluta para Gmail
        brazil_code = "73"

        # Verificar os números disponíveis no Brasil
        brazil_available = self.get_number_status(brazil_code, service)

        # Logar disponibilidade para Brasil
        logger.info(
            f"🇧🇷 Brasil: {brazil_available} números disponíveis para {service}")

        # PRIORIDADE 1: Se houver números no Brasil, retornar imediatamente
        if brazil_available > 0:
            prices = self.get_prices(service)
            if prices and brazil_code in prices and service in prices[brazil_code]:
                price = float(prices[brazil_code][service]['cost'])
            else:
                price = 0.0
            logger.info(
                f"✅ Usando Brasil com {brazil_available} números disponíveis")
            return brazil_code, price

        # Se não houver números no Brasil, verificar outros países
        logger.warning(
            f"⚠️ Brasil sem números disponíveis para {service}, verificando outros países")

        # Verificar disponibilidade em outros países da América do Sul
        country_availability = {}

        for country_code in self.country_priority[1:]:
            country_name = self.selected_countries[country_code]
            available = self.get_number_status(country_code, service)
            logger.info(f"{country_name}: {available} disponíveis")

            if available > 0:
                country_availability[country_code] = available

        # Se não houver números disponíveis em nenhum país
        if not country_availability:
            logger.error(
                f"❌ Nenhum número disponível em nenhum país para {service}")
            return None, None

        # Ordenar países disponíveis conforme prioridade
        for country_code in self.country_priority[1:]:
            if country_code in country_availability:
                available = country_availability[country_code]
                country_name = self.selected_countries[country_code]

                # Buscar preço
                prices = self.get_prices(service)
                if prices and country_code in prices and service in prices[country_code]:
                    price = float(prices[country_code][service]['cost'])
                    logger.warning(
                        f"⚠️ Usando {country_name} pois Brasil não está disponível ({available} números)")
                    return country_code, price

        # Não deveria chegar aqui, mas por segurança
        logger.error(f"❌ Falha ao selecionar país para {service}")
        return None, None

    def buy_number(self, service, country):
        """
        Compra um número de telefone, priorizando Brasil para Gmail.
        """
        # Brasil SEMPRE deve ser a prioridade absoluta para Gmail
        brazil_code = "73"
        force_brazil = service == "go"  # Força Brasil para Gmail

        try:
            if force_brazil:
                # Verificar números no Brasil
                brazil_available = self.get_number_status(brazil_code, service)

                if brazil_available > 0:
                    logger.info(
                        f"🇧🇷 Tentando comprar número no Brasil para {service}")
                    country_to_use = brazil_code
                else:
                    logger.warning(
                        f"⚠️ Brasil sem números disponíveis, tentando alternativo: {country}")
                    country_to_use = country
            else:
                country_to_use = country

            # Usar a SMSAPI para obter o número
            activation_id = None
            phone_number = None

            try:
                # Evitar que erros na API quebrem todo o processo
                result = self.sms_api.get_number(service, country_to_use)

                if result:
                    if isinstance(result, tuple) and len(result) == 2:
                        activation_id, phone_number = result

                    # Garantir que são strings
                    if activation_id is not None:
                        activation_id = str(activation_id)
                    if phone_number is not None:
                        phone_number = str(phone_number)
            except Exception as api_error:
                logger.error(
                    f"❌ Erro ao chamar API para comprar número: {str(api_error)}")
                return None, None

            # Processo seguro para validar os resultados
            if activation_id and phone_number:
                try:
                    country_name = self.selected_countries.get(
                        country_to_use, "Desconhecido")
                    formatted_phone = f"+{phone_number}"
                    logger.info(
                        f"✅ Número comprado com sucesso: {formatted_phone} (ID: {activation_id})")
                    logger.info(f"📍 País: {country_name}")

                    # Adicionar ao gerenciador
                    self.add_number(phone_number, country_to_use,
                                    activation_id, service)

                    # Retornar como tupla de strings
                    return activation_id, phone_number
                except Exception as e:
                    logger.error(
                        f"❌ Erro ao processar número comprado: {str(e)}")
                    return None, None

            # Se não conseguiu com Brasil e era forçado, tentar alternativo
            if force_brazil and country_to_use == brazil_code and country != brazil_code:
                logger.info(f"🔄 Tentando país alternativo: {country}")
                # Chamar recursivamente com o país alternativo
                return self.buy_number(service, country)
        except Exception as e:
            logger.error(f"❌ Erro ao comprar número: {str(e)}")

        logger.warning(
            f"❌ Não foi possível obter número para {service} em {country}")
        return None, None

    def get_number_status(self, country, service):
        """Verifica disponibilidade de números para um serviço em um país específico (com validação)."""
        try:
            # Chamar diretamente o método da SMSAPI
            status = self.sms_api.get_number_status(country, service)

            # Validar o retorno da API
            if not isinstance(status, int) and status is not None:
                logger.warning(
                    f"⚠️ Formato inválido retornado pela API para status: {type(status)}")
                return 0

            return status if status is not None else 0
        except Exception as e:
            logger.error(
                f"❌ Erro ao verificar disponibilidade de números: {str(e)}")
            return 0

    def get_prices(self, service=None):
        """
        Obtém preços dos números de telefone filtrados para os países selecionados.
        """
        try:
            def fetch_prices():
                try:
                    # Obter lista de países selecionados (com validação)
                    if not hasattr(self, 'selected_countries') or not self.selected_countries:
                        logger.warning(
                            "⚠️ Países selecionados não definidos corretamente")
                        countries = []
                    else:
                        countries = list(self.selected_countries.keys())

                    # Passar a lista de países selecionados para o SMSAPI
                    return self.sms_api.get_prices(service=service, countries=countries)
                except Exception as e:
                    logger.error(f"❌ Erro na função fetch_prices: {str(e)}")
                    return {}

            # Usar retry automático para obter preços
            all_prices = self.execute_with_retry(fetch_prices)

            if not all_prices:
                logger.error("❌ Não foi possível obter os preços da API")
                return {}

            return all_prices
        except Exception as e:
            logger.error(f"❌ Erro ao obter preços: {str(e)}")
            return {}  # Retornar dicionário vazio em vez de None

    def refresh_credentials(self):
        """Atualiza a chave da API."""
        self.api_key = self.load_api_key()
        self.sms_api.api_key = self.api_key
        return True

    def execute_with_retry(self, func, max_retries=3, retry_delay=2):
        """
        Executa uma função com retry automático em caso de falhas de conexão.

        Args:
            func: Função a ser executada
            max_retries: Número máximo de tentativas
            retry_delay: Tempo de espera entre tentativas (segundos)

        Returns:
            O resultado da função ou {} em caso de falha para dicionários, 0 para números
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                result = func()
                # Verificar se o resultado é None, e converter para um valor padrão apropriado
                if result is None:
                    logger.warning(
                        "⚠️ Função retornou None, convertendo para valor padrão")
                    return {} if isinstance(func, dict) else 0
                return result
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.RequestException) as e:
                last_error = e
                logger.warning(
                    f"⚠️ Tentativa {attempt+1}/{max_retries} falhou: {str(e)}")

                # Somente faz o log e aguarda se não for a última tentativa
                if attempt < max_retries - 1:
                    logger.info(
                        f"🔄 Aguardando {retry_delay}s antes da próxima tentativa...")
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"❌ Falha após {max_retries} tentativas: {str(e)}")
            except Exception as e:
                logger.error(f"❌ Erro não relacionado à conexão: {str(e)}")
                last_error = e
                # Não tentar novamente para erros não relacionados à conexão
                break

        # Se chegou aqui, todas as tentativas falharam
        logger.error(
            f"❌ Todas as tentativas falharam: {str(last_error) if last_error else 'Erro desconhecido'}")
        # Retornar valor vazio apropriado com base no tipo esperado
        return {}  # Assume dict como padrão, pois é o caso mais comum
