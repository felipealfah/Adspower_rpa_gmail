from enum import Enum
from dataclasses import dataclass
import time
import logging
import os
import glob
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .exceptions import (
    TermsAcceptanceError,
    ElementInteractionError,
    NavigationError
)
from .config import timeouts
from .locators import terms_locators

logger = logging.getLogger(__name__)


class TermsState(Enum):
    """Estados possíveis do processo de aceitação dos termos."""
    INITIAL = "initial"
    TERMS_PAGE = "terms_page"
    TERMS_ACCEPTED = "terms_accepted"
    CONFIRMATION_HANDLED = "confirmation_handled"
    RECOVERY_SKIPPED = "recovery_skipped"
    REVIEW_COMPLETED = "review_completed"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TermsInfo:
    """Armazena informações sobre o processo de aceitação dos termos."""
    state: TermsState = TermsState.INITIAL
    terms_accepted: bool = False
    confirmation_handled: bool = False
    recovery_skipped: bool = False
    review_completed: bool = False
    attempts: int = 0
    max_attempts: int = 3


class TermsHandler:
    """
    Gerencia o processo de aceitação de termos e revisão de conta.
    Responsável por aceitar os termos de uso e pular etapas opcionais.
    """

    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, timeouts.DEFAULT_WAIT)
        self.terms_info = TermsInfo()
        self.max_retries = 3
        self.retry_delay = 2

    def handle_terms_acceptance(self) -> bool:
        """Processo principal de aceitação dos termos com lógica revisada."""
        try:
            logger.info("📄 Iniciando processo após verificação de E-mail...")
            time.sleep(3)  # Aguardar carregamento completo da página

            # 1. Primeiro etapa: pular email de recuperação e tela de revisão
            if not self._skip_recovery_email():
                logger.warning(
                    "⚠️ Possível problema ao pular email de recuperação, mas continuando...")
            time.sleep(3)  # Aguardar carregamento

            # 2. Tela de revisão das informações
            if not self._handle_review_page():
                logger.warning(
                    "⚠️ Possível problema na tela de revisão, mas continuando...")

            time.sleep(3)  # Aguardar carregamento

            # Verificar URL atual para diagnóstico
            try:
                current_url = self.driver.current_url
                logger.info(f"🔗 URL atual: {current_url}")
            except:
                logger.warning("⚠️ Não foi possível obter a URL atual")

            # 3. Verificar se a tela "Privacy and Terms" carrega
            logger.info("📌 Tentando verificar tela 'Privacy and Terms'...")
            if self._handle_privacy_and_terms_screen():
                logger.info("✅ Tela 'Privacy and Terms' identificada!")
                # Verificar se a conta foi criada com sucesso
                account_created = self._check_account_created()
                if account_created:
                    # Limpar os screenshots se a conta foi criada
                    self._delete_screenshots()
                return True  # Se a tela carregar e o botão for clicado, sucesso

            logger.warning(
                "⚠️ Tela 'Privacy and Terms' não encontrada, verificando tipo de tela...")

            # 4. Verificar se estamos na tela tradicional ou na tela com checkboxes
            logger.info("📌 Verificando tipo de tela...")

            # Salvar screenshot para diagnóstico
            try:
                self._save_screenshot("before_terms_detection")
            except:
                pass

            # Tentar definir qual tipo de tela está sendo exibida
            is_traditional = self._is_traditional_terms_screen()
            is_checkbox = self._is_checkbox_terms_screen()

            # Log para diagnóstico
            logger.info(
                f"📊 Detecção: Tela tradicional: {is_traditional}, Tela de checkboxes: {is_checkbox}")

            success = False

            if is_traditional:
                logger.info("✅ Detectada tela tradicional de termos.")

                # Tentar clicar no botão "Concordo"
                if self._click_agree_button():
                    logger.info(
                        "✅ Botão 'Concordo' clicado com sucesso, verificando modal de confirmação...")

                    # Verificar se o modal de confirmação aparece
                    if self._handle_confirmation_modal():
                        logger.info(
                            "✅ Modal de confirmação tratado com sucesso!")
                        success = True
                    else:
                        # O modal pode não ter aparecido porque a conta já foi criada diretamente
                        logger.info(
                            "🔍 Modal não encontrado, verificando se avançamos...")
                        time.sleep(3)  # Aguardar processamento

                        # Verificar indicadores de que já passamos dessa tela
                        account_created = self._check_account_created()
                        if account_created:
                            success = True

                        # Verificar se ainda estamos na mesma tela
                        still_on_terms = self._is_traditional_terms_screen()
                        if not still_on_terms:
                            logger.info(
                                "✅ Avançamos da tela de termos tradicional com sucesso!")
                            success = True

            elif is_checkbox:
                logger.info("✅ Detectada tela de termos com checkboxes")

                # Tentar marcar os checkboxes e clicar no botão
                if self._handle_checkbox_terms():
                    logger.info(
                        "✅ Termos com checkboxes tratados com sucesso!")
                    success = True

            else:
                # Se não conseguiu identificar o tipo de tela, tentar ambas as abordagens
                logger.warning(
                    "⚠️ Tipo de tela não identificado, tentando ambas as abordagens...")

                # Tentar abordagem de tela tradicional primeiro
                if self._click_agree_button():
                    logger.info(
                        "✅ Botão 'Concordo' clicado com abordagem tradicional")

                    # Verificar se o modal aparece
                    if self._handle_confirmation_modal():
                        logger.info("✅ Modal tratado com sucesso!")
                        success = True

                    # Verificar se avançamos mesmo sem modal
                    time.sleep(3)
                    success_indicators = [
                        "//img[contains(@alt, 'Google')]",
                        "//a[contains(@href, 'mail.google.com')]"
                    ]

                    for indicator in success_indicators:
                        if self._element_exists(indicator, timeout=2):
                            logger.info("✅ Avançamos sem modal!")
                            success = True

                # Se não funcionou, tentar abordagem de checkboxes
                if self._handle_checkbox_terms():
                    logger.info("✅ Checkboxes tratados com sucesso!")
                    success = True

                logger.error(
                    "❌ Nenhuma abordagem funcionou para tratar os termos.")
                success = False

            # Se a conta foi criada com sucesso, apagar os screenshots
            if success:
                account_created = self._check_account_created()
                if account_created:
                    self._delete_screenshots()

            return success

        except Exception as e:
            logger.error(
                f"❌ Erro durante processo de aceitação de termos: {str(e)}")
            raise TermsAcceptanceError(
                f"Falha no processo de aceitação de termos: {str(e)}")

    def _is_checkbox_terms_screen(self) -> bool:
        """Verifica se estamos na tela de termos com checkboxes."""
        try:
            # Verificar indicadores de texto específicos para checkboxes
            checkbox_text_indicators = [
                "//div[contains(text(), 'Concordo com')]",
                "//span[contains(text(), 'Concordo com')]",
                "//div[contains(text(), 'Aceito os')]",
                "//span[contains(text(), 'Aceito os')]",
                "//div[contains(text(), 'I agree to')]",
                "//span[contains(text(), 'I agree to')]",
                "//div[contains(text(), 'I accept the')]",
                "//span[contains(text(), 'I accept the')]",
                "//div[contains(text(), 'Estoy de acuerdo con')]",
                "//span[contains(text(), 'Estoy de acuerdo con')]"
            ]

            # Verificar indicadores de texto
            for indicator in checkbox_text_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info(
                        f"✅ Indicador de texto para checkboxes encontrado: {indicator}")
                    return True

            # Verificar elementos de checkbox
            for checkbox in terms_locators.CHECKBOX_INPUTS:
                if self._element_exists(checkbox, timeout=2):
                    logger.info(
                        f"✅ Elemento de checkbox encontrado: {checkbox}")
                    return True

            # Verificar o botão típico de tela de checkboxes (geralmente "Concordo")
            checkbox_button_indicators = [
                "//button[contains(text(), 'Concordo') and contains(@class, 'VfPpkd-LgbsSe')]",
                "//button[contains(text(), 'I agree') and contains(@class, 'VfPpkd-LgbsSe')]",
                "//button[contains(text(), 'Acepto') and contains(@class, 'VfPpkd-LgbsSe')]"
            ]

            for indicator in checkbox_button_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info(
                        f"✅ Botão típico de tela com checkboxes encontrado: {indicator}")
                    return True

            logger.info(
                "📌 Não foram encontrados indicadores de tela de checkboxes")
            return False

        except Exception as e:
            logger.error(f"❌ Erro ao verificar tela de checkboxes: {str(e)}")
            return False

    def _handle_checkbox_terms(self) -> bool:
        """Manipula especificamente os checkboxes e botão da tela de termos."""
        try:
            logger.info("📌 Tentando marcar checkboxes e confirmar termos...")

            # Marcar cada checkbox, com foco nos elementos de label (mais clicáveis)
            checkboxes_marked = True

            # Lista de possíveis elementos clicáveis relacionados aos checkboxes
            checkbox_areas = [
                # Primeiro, tentar elementos de label (geralmente mais fáceis de clicar)
                "//div[contains(text(), 'Concordo com')]/preceding::label[1]",
                "//div[contains(text(), 'Concordo com')]/ancestor::label",
                "//span[contains(text(), 'Concordo com')]/preceding::label[1]",
                "//span[contains(text(), 'Concordo com')]/ancestor::label",
                # Depois, tentar elementos de checkbox específicos
            ] + terms_locators.CHECKBOX_INPUTS

            # Tentar clicar em cada área
            for area_xpath in checkbox_areas:
                if self._element_exists(area_xpath, timeout=2):
                    try:
                        # Tentar obter o elemento
                        element = self.driver.find_element(
                            By.XPATH, area_xpath)

                        # Scrollar até o elemento
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", element)
                        time.sleep(1)

                        # Tentar clicar com diferentes métodos
                        try:
                            # Método 1: Clique direto
                            element.click()
                            logger.info(
                                f"✅ Clique direto bem-sucedido em: {area_xpath}")
                        except Exception as e1:
                            logger.warning(
                                f"⚠️ Clique direto falhou: {str(e1)}")
                            try:
                                # Método 2: Clique via JavaScript
                                self.driver.execute_script(
                                    "arguments[0].click();", element)
                                logger.info(
                                    f"✅ Clique via JavaScript bem-sucedido em: {area_xpath}")
                            except Exception as e2:
                                logger.error(
                                    f"❌ Ambos os métodos de clique falharam para: {area_xpath}")
                                checkboxes_marked = False
                    except Exception as e:
                        logger.error(
                            f"❌ Erro ao interagir com elemento {area_xpath}: {str(e)}")
                        checkboxes_marked = False

            # Se não conseguiu marcar todos os checkboxes, registrar erro
            if not checkboxes_marked:
                logger.warning(
                    "⚠️ Problemas ao marcar alguns checkboxes, mas continuando...")

            # BOTÃO DE CRIAR CONTA - Tentar clicar no botão mais específico "Criar conta"
            # Lista prioritária de botões a tentar, começando com mais específicos
            account_creation_buttons = [
                # Botões específicos para criar conta (traduzidos)
                "//button[contains(text(), 'Criar conta')]",
                "//button[contains(text(), 'Create account')]",
                "//button[contains(text(), 'Crear cuenta')]",
                # Caminho absoluto para botão final
                "/html/body/div[1]/div[1]/div[2]/c-wiz/div/div[3]/div/div[1]/div/div/button"
            ] + terms_locators.CONFIRM_BUTTON_XPATHS  # Adicionar botões genéricos por último

            # Tentar clicar no botão de confirmação/criar conta
            button_clicked = False

            for button_xpath in account_creation_buttons:
                if self._element_exists(button_xpath, timeout=2):
                    try:
                        logger.info(
                            f"🔍 Tentando clicar em botão: {button_xpath}")
                        button = self.driver.find_element(
                            By.XPATH, button_xpath)

                        # Scrollar até o botão
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(1)

                        # Tentar clicar com diferentes métodos
                        try:
                            # Verificar visibilidade e status habilitado
                            if not button.is_displayed() or not button.is_enabled():
                                logger.warning(
                                    f"⚠️ Botão {button_xpath} não está visível ou habilitado")
                                continue

                            # Registrar texto do botão se houver
                            button_text = button.text.strip() if button.text else "Sem texto"
                            logger.info(f"📝 Texto do botão: '{button_text}'")

                            # Método 1: Clique direto
                            button.click()
                            logger.info(
                                f"✅ Clique direto bem-sucedido no botão: {button_text}")
                            button_clicked = True
                            break
                        except Exception as e1:
                            logger.warning(
                                f"⚠️ Clique direto no botão falhou: {str(e1)}")
                            try:
                                # Método 2: Clique via JavaScript
                                self.driver.execute_script(
                                    "arguments[0].click();", button)
                                logger.info(
                                    f"✅ Clique via JavaScript bem-sucedido no botão: {button_text}")
                                button_clicked = True
                                break
                            except Exception as e2:
                                logger.error(
                                    f"❌ Ambos os métodos de clique falharam para o botão: {button_xpath}")
                    except Exception as e:
                        logger.error(
                            f"❌ Erro ao interagir com botão {button_xpath}: {str(e)}")

            if not button_clicked:
                logger.error(
                    "❌ Não foi possível clicar no botão 'Criar conta'")

                # Tentar encontrar TODOS os botões na página e registrar para diagnóstico
                try:
                    all_buttons = self.driver.find_elements(
                        By.XPATH, "//button")
                    logger.info(
                        f"📊 Total de botões na página: {len(all_buttons)}")

                    for i, btn in enumerate(all_buttons):
                        if btn.is_displayed():
                            btn_text = btn.text.strip() if btn.text else "Sem texto"
                            btn_class = btn.get_attribute("class")
                            logger.info(
                                f"📝 Botão #{i+1}: Texto='{btn_text}', Class='{btn_class}'")
                except Exception as e:
                    logger.error(f"❌ Erro ao listar botões: {str(e)}")

                # Tentar clicar em qualquer botão na página como último recurso
                try:
                    last_resort_button = "//button[contains(@class, 'VfPpkd-LgbsSe')]"
                    if self._element_exists(last_resort_button, timeout=1):
                        buttons = self.driver.find_elements(
                            By.XPATH, last_resort_button)
                        for i, btn in enumerate(buttons):
                            if btn.is_displayed() and btn.is_enabled():
                                logger.warning(
                                    f"⚠️ Tentando clicar em botão genérico #{i+1} como último recurso")
                                btn_text = btn.text.strip() if btn.text else "Sem texto"
                                logger.info(
                                    f"📝 Texto do botão genérico: '{btn_text}'")

                                try:
                                    # Garantir que está visível
                                    self.driver.execute_script(
                                        "arguments[0].scrollIntoView({block: 'center'});", btn)
                                    time.sleep(1)

                                    self.driver.execute_script(
                                        "arguments[0].click();", btn)
                                    logger.info(
                                        f"✅ Clicado em botão genérico #{i+1}")
                                    button_clicked = True

                                    # Salvar screenshot após clicar no botão
                                    self._save_screenshot(
                                        "after_generic_button_click")
                                    time.sleep(3)
                                    break
                                except Exception as e:
                                    logger.error(
                                        f"❌ Falha ao clicar no botão genérico #{i+1}: {str(e)}")
                except Exception as e:
                    logger.error(f"❌ Falha ao tentar último recurso: {str(e)}")

                if not button_clicked:
                    return False

            # Aguardar processamento após o clique no botão
            logger.info("🕒 Aguardando processamento após clique no botão...")
            # Tempo mais longo para garantir processamento completo
            time.sleep(7)

            # Verificar se ainda estamos na mesma tela
            # Usar apenas os primeiros indicadores de texto
            for area_xpath in checkbox_areas[:4]:
                if self._element_exists(area_xpath, timeout=2):
                    logger.error(
                        "❌ Ainda estamos na tela de checkboxes. O processo não avançou após o clique no botão.")

                    # Tentar um último clique em botão com texto exato "Criar conta" usando match exato
                    try:
                        exact_button = self.driver.find_element(
                            By.XPATH, "//button[.='Criar conta']")
                        if exact_button.is_displayed() and exact_button.is_enabled():
                            logger.warning(
                                "⚠️ Tentando último recurso: clique em botão exato 'Criar conta'")
                            self.driver.execute_script(
                                "arguments[0].click();", exact_button)
                            time.sleep(5)

                            # Verificar se ainda estamos na mesma tela novamente
                            still_on_page = False
                            for check_xpath in checkbox_areas[:2]:
                                if self._element_exists(check_xpath, timeout=1):
                                    still_on_page = True
                                    break

                            if still_on_page:
                                logger.error(
                                    "❌ Ainda estamos na tela de checkboxes após última tentativa.")
                                # Salvar screenshot final em caso de falha
                                self._save_screenshot("failed_final_attempt")
                                return False
                            else:
                                logger.info("✅ Última tentativa bem-sucedida!")
                    except Exception as e:
                        logger.error(f"❌ Falha na última tentativa: {str(e)}")
                        # Salvar screenshot final em caso de falha
                        self._save_screenshot("failed_last_attempt")
                        return False

            # Verificar se um dos elementos após a criação da conta está presente
            success_indicators = [
                # Possíveis telas após a criação bem-sucedida da conta
                # Logo do Google na página inicial
                "//img[contains(@alt, 'Google')]",
                "//a[contains(@href, 'mail.google.com')]",  # Link para o Gmail
                "//div[contains(text(), 'Sua conta Google foi criada')]",
                "//div[contains(text(), 'Your Google Account was created')]",
                "//div[contains(text(), 'Se ha creado tu Cuenta de Google')]"
            ]

            for indicator in success_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info("✅ Detectado elemento pós-criação de conta!")
                    return True

            logger.info("✅ Avançamos da tela de checkboxes com sucesso!")
            return True

        except Exception as e:
            logger.error(f"❌ Erro ao manipular checkboxes: {str(e)}")
            return False

    def _accept_terms(self) -> bool:
        """Aceita os termos de uso com suporte a múltiplos formatos de tela."""
        try:
            logger.info("📌 Localizando botão 'Aceitar' nos termos de uso...")

            # Tenta cada XPath até encontrar um que funcione
            for xpath in terms_locators.ACCEPT_BUTTON_XPATHS:
                try:
                    if self._element_exists(xpath, timeout=2):
                        agree_button = self.driver.find_element(
                            By.XPATH, xpath)
                        if agree_button.is_displayed() and agree_button.is_enabled():
                            logger.info(
                                f"✅ Botão 'Aceitar' encontrado com XPath: {xpath}")

                            # Tenta clicar com JavaScript para maior confiabilidade
                            self.driver.execute_script(
                                "arguments[0].click();", agree_button)
                            time.sleep(2)

                            logger.info("✅ Termos aceitos com sucesso.")
                            self.terms_info.terms_accepted = True
                            return True
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao tentar clicar em {xpath}: {str(e)}")
                    continue

            # Se chegou aqui, nenhum botão foi encontrado
            logger.error("❌ Botão de aceite dos termos não encontrado.")
            return False

        except Exception as e:
            logger.error(f"❌ Erro ao aceitar termos: {str(e)}")
            return False

    def _handle_confirmation_modal(self) -> bool:
        """Verifica se há um modal de confirmação e lida com ele."""
        try:
            logger.info("📌 Verificando se há um modal de confirmação...")

            # Esperar um pouco para o modal aparecer completamente
            time.sleep(2)

            # Tenta encontrar o botão de confirmação usando o localizador
            if self._element_exists(terms_locators.CONFIRM_BUTTON, timeout=2):
                confirm_button = self.driver.find_element(
                    By.XPATH, terms_locators.CONFIRM_BUTTON)

                # Rolar até o botão para garantir que está visível
                self.driver.execute_script(
                    "arguments[0].scrollIntoView(true);", confirm_button)
                # Pequena pausa para garantir que o scroll terminou
                time.sleep(1)

                # Clicar no botão de confirmação
                confirm_button.click()
                logger.info("✅ Modal de confirmação fechado com sucesso.")
                self.terms_info.confirmation_handled = True
                time.sleep(2)  # Espera para processamento
                return True

            logger.info(
                "✅ Nenhum modal de confirmação encontrado, continuando...")
            self.terms_info.confirmation_handled = True
            return True

        except Exception as e:
            logger.error(f"❌ Erro ao verificar modal de confirmação: {str(e)}")
            return False

    def _handle_review_page(self) -> bool:
        """Confirma o número de telefone na tela de revisão."""
        try:
            logger.info(
                "📌 Verificando tela de confirmação de dados do usuário...")

            # Tenta cada XPath
            button_clicked = False
            for xpath in terms_locators.NEXT_BUTTON_XPATHS:
                try:
                    if self._element_exists(xpath, timeout=3):
                        next_button = self.driver.find_element(By.XPATH, xpath)
                        if next_button.is_displayed() and next_button.is_enabled():
                            # Tenta clicar no botão com JavaScript para maior confiabilidade
                            self.driver.execute_script(
                                "arguments[0].click();", next_button)
                            time.sleep(2)
                            logger.info(
                                f"✅ Clicou no botão de confirmação de telefone: {xpath}")
                            button_clicked = True
                            break
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao clicar em botão {xpath}: {str(e)}")
                    continue

            if not button_clicked:
                logger.warning(
                    "⚠️ Nenhum botão de confirmação de telefone clicado, mas continuando...")

            self.terms_info.review_completed = True
            return True

        except Exception as e:
            logger.error(f"❌ Erro na tela de revisão: {str(e)}")
            return False

    def _click_agree_button(self) -> bool:
        """Clica no botão 'I agree'."""
        try:
            logger.info("📌 Tentando localizar e clicar no botão 'Concordo'...")

            # Salvar screenshot antes de tentar clicar
            self._save_screenshot("before_click_agree")

            # Registrar texto da página para diagnóstico
            try:
                page_text = self.driver.find_element(By.TAG_NAME, "body").text
                logger.info(
                    f"📄 Trecho do texto da página: {page_text[:200]}...")
            except:
                logger.warning(
                    "⚠️ Não foi possível capturar o texto da página")

            # Lista de botões de aceitação por prioridade
            priority_buttons = [
                "//button[contains(text(), 'Concordo')]",
                "//button[contains(text(), 'I agree')]",
                "//button[contains(text(), 'Acepto')]",
                "//div[@role='button' and contains(text(), 'Concordo')]",
                "//div[@role='button' and contains(text(), 'I agree')]",
                "//div[@role='button' and contains(text(), 'Acepto')]",
                "//span[contains(text(), 'Concordo')]/ancestor::button",
                "//span[contains(text(), 'I agree')]/ancestor::button",
                "//span[contains(text(), 'Acepto')]/ancestor::button"
            ] + terms_locators.ACCEPT_BUTTON_XPATHS

            # Primeiro, listar todos os botões encontrados para diagnóstico
            buttons_found = []

            for xpath in priority_buttons:
                try:
                    elements = self.driver.find_elements(By.XPATH, xpath)
                    if elements:
                        for i, element in enumerate(elements):
                            if element.is_displayed():
                                text = element.text.strip() if element.text else "Sem texto"
                                css_class = element.get_attribute("class")
                                buttons_found.append({
                                    "xpath": xpath,
                                    "index": i,
                                    "text": text,
                                    "class": css_class
                                })
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao verificar botão {xpath}: {str(e)}")

            # Logar botões encontrados
            if buttons_found:
                logger.info(
                    f"🔍 Total de botões encontrados: {len(buttons_found)}")
                for i, btn in enumerate(buttons_found):
                    logger.info(
                        f"📝 Botão #{i+1}: XPath='{btn['xpath']}', Texto='{btn['text']}', Classe='{btn['class']}'")
            else:
                logger.warning(
                    "⚠️ Nenhum botão encontrado com os XPaths especificados")

            # Tentar clicar em cada botão na ordem de prioridade
            for xpath in priority_buttons:
                if self._element_exists(xpath, timeout=2):
                    buttons = self.driver.find_elements(By.XPATH, xpath)

                    for button in buttons:
                        if button.is_displayed() and button.is_enabled():
                            # Registrar informações do botão
                            button_text = button.text.strip() if button.text else "Sem texto"
                            css_class = button.get_attribute("class")
                            logger.info(
                                f"🎯 Tentando clicar no botão: '{button_text}' (Classe: {css_class})")

                            # Scrollar até o botão
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", button)
                            time.sleep(1)

                            # Salvar screenshot do botão
                            self._save_screenshot("button_before_click")

                            try:
                                # Tentar clicar diretamente primeiro
                                button.click()
                                logger.info(
                                    f"✅ Clique direto bem-sucedido no botão 'Concordo': {button_text}")

                                # Salvar screenshot após o clique
                                self._save_screenshot("after_direct_click")

                                # Esperar para ver se o modal aparece
                                time.sleep(2)
                                return True
                            except Exception as e1:
                                logger.warning(
                                    f"⚠️ Clique direto falhou: {str(e1)}")
                                try:
                                    # Tentar clicar usando JavaScript
                                    self.driver.execute_script(
                                        "arguments[0].click();", button)
                                    logger.info(
                                        f"✅ Clique via JavaScript bem-sucedido no botão 'Concordo': {button_text}")

                                    # Salvar screenshot após o clique
                                    self._save_screenshot("after_js_click")

                                    # Esperar para ver se o modal aparece
                                    time.sleep(2)
                                    return True
                                except Exception as e2:
                                    logger.error(
                                        f"❌ Falha em ambos os métodos de clique para: {xpath} - {button_text}")

            # Se chegou aqui, nenhum botão foi encontrado
            logger.error("❌ Nenhum botão 'Concordo' encontrado ou clicado.")

            # Tentar um último recurso extremo: buscar qualquer botão na página
            try:
                all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                logger.info(
                    f"🔄 Último recurso: encontrados {len(all_buttons)} botões na página")

                for i, btn in enumerate(all_buttons):
                    if btn.is_displayed() and btn.is_enabled():
                        text = btn.text.strip() if btn.text else "Sem texto"
                        logger.info(
                            f"🔄 Tentando clicar no botão genérico #{i+1}: {text}")

                        try:
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block: 'center'});", btn)
                            time.sleep(1)
                            self.driver.execute_script(
                                "arguments[0].click();", btn)
                            logger.info(
                                f"✅ Último recurso bem-sucedido no botão: {text}")

                            # Salvar screenshot após o clique
                            self._save_screenshot("after_last_resort_click")

                            return True
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Falha no último recurso para botão #{i+1}: {str(e)}")
            except Exception as e:
                logger.error(f"❌ Erro no último recurso: {str(e)}")

            return False

        except Exception as e:
            logger.error(f"❌ Erro ao clicar no botão 'I agree': {str(e)}")
            return False

    def _handle_privacy_and_terms_screen(self) -> bool:
        """Verifica se a tela 'Privacy and Terms' é exibida e trata-a."""
        try:
            logger.info(
                "📌 Verificando se a tela de Termos e Privacidade é exibida...")

            # Salvar screenshot da tela atual
            self._save_screenshot("privacy_terms_detection")

            # Aguardar um momento para a tela carregar completamente
            time.sleep(2)

            # Lista de indicadores de tela de privacidade e termos
            privacy_terms_indicators = [
                "//h1[contains(text(), 'Termos e Privacidade')]",
                "//h1[contains(text(), 'Terms and Privacy')]",
                "//h1[contains(text(), 'Términos y Privacidad')]",
                "//div[contains(text(), 'Privacidade e Termos')]",
                "//div[contains(text(), 'Privacy and Terms')]",
                "//div[contains(text(), 'Privacidad y Condiciones')]"
            ]

            privacy_terms_found = False
            identified_indicator = None

            # Verificar cada indicador
            for indicator in privacy_terms_indicators:
                if self._element_exists(indicator, timeout=2):
                    privacy_terms_found = True
                    identified_indicator = indicator
                    logger.info(
                        f"✅ Tela de 'Termos e Privacidade' identificada com: {indicator}")
                    break

            if not privacy_terms_found:
                logger.warning(
                    "⚠️ Tela de 'Termos e Privacidade' não encontrada.")
                return False  # A tela não foi encontrada

            # Se identificamos a tela, tentar clicar no botão para avançar
            logger.info(
                "🔍 Tela de Termos e Privacidade encontrada. Procurando botão 'Concordo'...")

            # XPath exato do botão "Concordo" fornecido pelo usuário
            specific_button_xpath = "/html/body/div[1]/div[1]/div[2]/c-wiz/div/div[3]/div/div[1]/div/div/button"
            specific_button_div_xpath = "/html/body/div[1]/div[1]/div[2]/c-wiz/div/div[3]/div/div[1]/div/div/button/div[3]"

            # Tentar primeiro o botão específico
            button_clicked = False

            if self._element_exists(specific_button_xpath, timeout=3):
                try:
                    logger.info("✅ Encontrado o botão exato de 'Concordo'!")
                    button = self.driver.find_element(
                        By.XPATH, specific_button_xpath)

                    # Verificar se está visível
                    if button.is_displayed() and button.is_enabled():
                        # Log do texto do botão
                        button_text = button.text.strip() if button.text else "Sem texto"
                        logger.info(
                            f"📝 Texto do botão encontrado: '{button_text}'")

                        # Scrollar até o botão
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", button)
                        time.sleep(1)

                        # Salvar screenshot antes do clique
                        self._save_screenshot("before_concordo_button_click")

                        # Tentar clique direto
                        button.click()
                        logger.info(
                            "✅ Clique direto bem-sucedido no botão 'Concordo'")
                        button_clicked = True

                        # Salvar screenshot após o clique
                        self._save_screenshot("after_concordo_button_click")
                    else:
                        logger.warning(
                            "⚠️ Botão 'Concordo' não está visível ou habilitado")
                except Exception as e:
                    logger.warning(
                        f"⚠️ Erro ao clicar diretamente no botão 'Concordo': {str(e)}")
                    try:
                        # Tentar via JavaScript
                        logger.info(
                            "🔄 Tentando clicar via JavaScript no botão 'Concordo'")
                        self.driver.execute_script(
                            "arguments[0].click();", button)
                        logger.info(
                            "✅ Clique via JavaScript bem-sucedido no botão 'Concordo'")
                        button_clicked = True

                        # Salvar screenshot após o clique
                        self._save_screenshot("after_concordo_js_button_click")
                    except Exception as e2:
                        logger.error(
                            f"❌ Falha também ao clicar via JavaScript: {str(e2)}")

            # Se o XPath específico não funcionou, tentar o XPath alternativo apenas do div[3]
            if not button_clicked and self._element_exists(specific_button_div_xpath, timeout=2):
                try:
                    logger.info(
                        "✅ Encontrado o div[3] dentro do botão 'Concordo'!")
                    button_div = self.driver.find_element(
                        By.XPATH, specific_button_div_xpath)

                    # Verificar texto para confirmar
                    button_div_text = button_div.text.strip() if button_div.text else "Sem texto"
                    logger.info(f"📝 Texto do div[3]: '{button_div_text}'")

                    # Tentar clicar no elemento pai (o botão)
                    parent_button = self.driver.execute_script(
                        "return arguments[0].parentNode;", button_div)

                    if parent_button:
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});", parent_button)
                        time.sleep(1)

                        # Salvar screenshot antes do clique
                        self._save_screenshot("before_concordo_div_click")

                        self.driver.execute_script(
                            "arguments[0].click();", parent_button)
                        logger.info(
                            "✅ Clique via JavaScript bem-sucedido no botão pai do div[3]")
                        button_clicked = True

                        # Salvar screenshot após o clique
                        self._save_screenshot("after_concordo_div_click")
                except Exception as e:
                    logger.error(
                        f"❌ Erro ao tentar clicar através do div[3]: {str(e)}")

            # Lista genérica de possíveis botões se os específicos não funcionarem
            if not button_clicked:
                logger.warning(
                    "⚠️ Botão específico não encontrado, tentando alternativas...")

                # Lista de possíveis botões para avançar (agora priorizando botões "Concordo")
                next_buttons = [
                    # Botões "Concordo/I agree/Acepto" com maior prioridade
                    "//button[normalize-space(text())='Concordo']",
                    "//button[normalize-space(text())='I agree']",
                    "//button[normalize-space(text())='Acepto']",
                    "//button[contains(text(), 'Concordo')]",
                    "//button[contains(text(), 'I agree')]",
                    "//button[contains(text(), 'Acepto')]",
                    "//div[@role='button' and contains(text(), 'Concordo')]",
                    "//div[@role='button' and contains(text(), 'I agree')]",
                    "//div[@role='button' and contains(text(), 'Acepto')]",
                    # Outros botões com menor prioridade
                    "//button[contains(text(), 'Avançar')]",
                    "//button[contains(text(), 'Next')]",
                    "//button[contains(text(), 'Siguiente')]",
                    "//button[contains(@class, 'VfPpkd-LgbsSe')]",
                    "//div[@role='button']"
                ]

                # Tenta cada botão na ordem de prioridade
                for btn_xpath in next_buttons:
                    try:
                        buttons = self.driver.find_elements(
                            By.XPATH, btn_xpath)

                        for i, button in enumerate(buttons):
                            if button.is_displayed() and button.is_enabled():
                                button_text = button.text.strip() if button.text else "Sem texto"

                                # Ignorar botões que claramente NÃO são o botão "Concordo"
                                if button_text and button_text in ["Mais opções", "More options", "Más opciones"]:
                                    logger.info(
                                        f"⏭️ Ignorando botão '{button_text}' - não é o botão de concordar")
                                    continue

                                logger.info(
                                    f"🎯 Tentando clicar no botão: '{button_text}' (XPath: {btn_xpath})")

                                # Scrollar até o botão
                                self.driver.execute_script(
                                    "arguments[0].scrollIntoView({block: 'center'});", button)
                                time.sleep(1)

                                # Salvar screenshot antes do clique
                                self._save_screenshot(
                                    f"privacy_terms_before_click_{i}")

                                try:
                                    # Tentar clique direto
                                    button.click()
                                    logger.info(
                                        f"✅ Clique direto bem-sucedido no botão: {button_text}")
                                    button_clicked = True

                                    # Salvar screenshot após o clique
                                    self._save_screenshot(
                                        f"privacy_terms_after_click_{i}")
                                    break
                                except Exception as e1:
                                    logger.warning(
                                        f"⚠️ Clique direto falhou: {str(e1)}")

                                    try:
                                        # Tentar clique via JavaScript
                                        self.driver.execute_script(
                                            "arguments[0].click();", button)
                                        logger.info(
                                            f"✅ Clique via JavaScript bem-sucedido no botão: {button_text}")
                                        button_clicked = True

                                        # Salvar screenshot após o clique
                                        self._save_screenshot(
                                            f"privacy_terms_after_js_click_{i}")
                                        break
                                    except Exception as e2:
                                        logger.error(
                                            f"❌ Ambos os métodos de clique falharam: {str(e2)}")

                        if button_clicked:
                            break
                    except Exception as e:
                        logger.warning(
                            f"⚠️ Erro ao processar botão {btn_xpath}: {str(e)}")
                        continue

            # Verificar se conseguimos clicar em algum botão
            if button_clicked:
                logger.info(
                    "✅ Botão clicado na tela de Termos e Privacidade. Aguardando processamento...")
                time.sleep(5)  # Aguardar processamento após o clique

                # Verificar se ainda estamos na mesma tela
                still_on_page = False
                for indicator in privacy_terms_indicators:
                    if self._element_exists(indicator, timeout=2):
                        still_on_page = True
                        break

                if not still_on_page:
                    logger.info(
                        "✅ Avançamos da tela de Termos e Privacidade com sucesso!")
                    return True
                else:
                    logger.warning(
                        "⚠️ Ainda estamos na tela de Termos e Privacidade após o clique.")

                    # Verificar se há modal ou confirmação adicional
                    logger.info("🔍 Verificando se há modal de confirmação...")
                    if self._handle_confirmation_modal():
                        logger.info("✅ Modal tratado com sucesso!")
                        return True
                    else:
                        logger.error(
                            "❌ Não conseguimos avançar após clicar no botão.")
                        return False
            else:
                logger.error(
                    "❌ Não foi possível clicar em nenhum botão na tela de Termos e Privacidade.")
                return False

        except Exception as e:
            logger.error(
                f"❌ Erro ao lidar com a tela 'Privacy and Terms': {str(e)}")
            return False

    def _is_traditional_terms_screen(self) -> bool:
        """Verifica se estamos na tela tradicional de termos."""
        try:
            # Verificar elementos específicos da tela tradicional
            traditional_indicators = [
                "//h1[contains(text(), 'Termos e Privacidade')]",
                "//h1[contains(text(), 'Terms and Privacy')]",
                "//h1[contains(text(), 'Términos y Privacidad')]",
                # Típico da tela tradicional
                "//div[contains(@class, 'freebirdFormviewerViewItemsItemItem')]",
                "//div[contains(text(), 'Privacidade e Termos')]",
                "//div[contains(text(), 'Privacy and Terms')]",
                "//div[contains(text(), 'Privacidad y Condiciones')]"
            ]

            for indicator in traditional_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info(
                        f"✅ Indicador de tela tradicional encontrado: {indicator}")
                    return True

            # Se não encontrou nenhum indicador específico, verificar botão típico
            accept_button_indicators = [
                "//button[contains(text(), 'Concordo') and not(contains(@class, 'VfPpkd-LgbsSe'))]",
                "//button[contains(text(), 'I agree') and not(contains(@class, 'VfPpkd-LgbsSe'))]",
                "//button[contains(text(), 'Acepto') and not(contains(@class, 'VfPpkd-LgbsSe'))]"
            ]

            for indicator in accept_button_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info(
                        f"✅ Botão típico de tela tradicional encontrado: {indicator}")
                    return True

            logger.info(
                "📌 Não foram encontrados indicadores de tela tradicional")
            return False
        except Exception as e:
            logger.error(f"❌ Erro ao verificar tela tradicional: {str(e)}")
            return False

    def _element_exists(self, xpath, timeout=3):
        """Verifica se um elemento existe na página."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return True
        except TimeoutException:
            return False

    def _execute_with_retry(self, func) -> bool:
        """Executa uma função com sistema de retry."""
        for attempt in range(self.max_retries):
            try:
                func()
                return True
            except Exception as e:
                logger.warning(f"⚠️ Tentativa {attempt + 1} falhou: {str(e)}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                return False

    def _skip_recovery_email(self) -> bool:
        """Pula a tela de recuperação de email."""
        try:
            logger.info("📌 Verificando tela de email de recuperação (Skip)...")
            skip_button = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, terms_locators.RECOVERY_EMAIL_SKIP))
            )
            skip_button.click()
            logger.info("✅ Botão 'Skip' clicado com sucesso.")
            time.sleep(2)  # Pequena pausa

            return True
        except TimeoutException:
            logger.warning(
                "⚠️ Tela de email de recuperação não apareceu, continuando...")
            return True  # Continua o fluxo normalmente
        except Exception as e:
            logger.error(
                f"❌ Erro ao tentar pular email de recuperação: {str(e)}")
            return False

    def _save_screenshot(self, name):
        """Salva um screenshot para fins de depuração."""
        try:
            import os
            screenshot_dir = "logs/screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            filename = f"{screenshot_dir}/{name}_{timestamp}.png"
            self.driver.save_screenshot(filename)
            logger.info(f"📸 Screenshot salvo: {filename}")
        except Exception as e:
            logger.error(f"❌ Erro ao salvar screenshot: {str(e)}")
            # Continuar o fluxo mesmo se não conseguir salvar o screenshot

    def _check_account_created(self) -> bool:
        """Verifica se a conta foi criada com sucesso."""
        try:
            logger.info("🔍 Verificando se a conta foi criada com sucesso...")

            # Indicadores de criação bem-sucedida
            success_indicators = [
                # Logo do Google
                "//img[contains(@alt, 'Google')]",
                # Link para Gmail
                "//a[contains(@href, 'mail.google.com')]",
                "//div[contains(text(), 'conta Google foi criada')]",
                "//div[contains(text(), 'Google Account was created')]",
                "//div[contains(text(), 'Cuenta de Google')]",
                # Elemento principal da página após criação
                "//div[@role='main']"
            ]

            for indicator in success_indicators:
                if self._element_exists(indicator, timeout=2):
                    logger.info(
                        "✅ Conta criada com sucesso! Indicador encontrado: " + indicator)
                    return True

            # Verificar URL atual
            try:
                current_url = self.driver.current_url
                if "myaccount.google.com" in current_url or "accounts.google.com/signin" in current_url:
                    logger.info(
                        f"✅ Conta criada com sucesso! URL confirma: {current_url}")
                    return True
            except:
                pass

            logger.info(
                "⚠️ Não foram encontrados indicadores de criação bem-sucedida da conta")
            return False

        except Exception as e:
            logger.error(f"❌ Erro ao verificar criação da conta: {str(e)}")
            return False

    def _delete_screenshots(self) -> None:
        """Apaga todos os screenshots após a confirmação da criação da conta."""
        try:
            logger.info("🧹 Iniciando limpeza dos screenshots...")
            screenshot_dir = "logs/screenshots"

            if not os.path.exists(screenshot_dir):
                logger.info(
                    "✅ Nenhum diretório de screenshots encontrado para limpar")
                return

            # Obtém todos os arquivos PNG no diretório de screenshots
            files = glob.glob(f"{screenshot_dir}/*.png")

            if not files:
                logger.info("✅ Nenhum screenshot encontrado para apagar")
                return

            count = 0
            for file in files:
                try:
                    os.remove(file)
                    count += 1
                except Exception as e:
                    logger.warning(
                        f"⚠️ Não foi possível apagar o arquivo {file}: {str(e)}")

            logger.info(f"✅ {count} screenshots apagados com sucesso")

        except Exception as e:
            logger.error(f"❌ Erro ao apagar screenshots: {str(e)}")
