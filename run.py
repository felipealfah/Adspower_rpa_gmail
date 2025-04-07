# run_services.py
import subprocess
import os
import sys
import time
import signal
import platform

# Armazenar os processos para encerramento adequado
processes = []

def clear_screen():
    """Limpa a tela do terminal."""
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")

def get_python_executable():
    """Retorna o executável Python adequado."""
    return sys.executable

def start_webhook():
    """Inicia o servidor webhook."""
    python_exe = get_python_executable()
    webhook_script = os.path.join("webhooks", "webhook.py")
    
    print("📲 Iniciando servidor webhook...")
    
    # Diferente tratamento para Windows vs Unix
    if platform.system() == "Windows":
        # No Windows, usamos subprocess.CREATE_NEW_CONSOLE para ter uma janela separada
        process = subprocess.Popen(
            [python_exe, webhook_script],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        # Em sistemas Unix, redirecionamos a saída para um arquivo de log
        log_file = open("webhook.log", "w")
        process = subprocess.Popen(
            [python_exe, webhook_script],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
    
    processes.append(("webhook", process))
    return process

def start_streamlit():
    """Inicia a aplicação Streamlit."""
    streamlit_app = os.path.join("ui", "app.py")
    
    print("🖥️ Iniciando aplicação Streamlit...")
    
    # Diferente tratamento para Windows vs Unix
    if platform.system() == "Windows":
        # No Windows, usamos subprocess.CREATE_NEW_CONSOLE para ter uma janela separada
        process = subprocess.Popen(
            ["streamlit", "run", streamlit_app],
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
    else:
        # Em sistemas Unix, redirecionamos a saída para um arquivo de log
        log_file = open("streamlit.log", "w")
        process = subprocess.Popen(
            ["streamlit", "run", streamlit_app],
            stdout=log_file,
            stderr=subprocess.STDOUT
        )
    
    processes.append(("streamlit", process))
    return process

def shutdown_handler(signum=None, frame=None):
    """Manipulador para encerrar todos os processos."""
    print("\n🛑 Encerrando serviços...")
    
    for name, process in processes:
        if process.poll() is None:  # Se o processo ainda estiver em execução
            print(f"  - Encerrando {name}...")
            
            if platform.system() == "Windows":
                # No Windows, usamos taskkill para garantir que o processo seja encerrado
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(process.pid)])
            else:
                # Em sistemas Unix, usamos o sinal SIGTERM
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()  # Força o encerramento se demorar demais
    
    print("✅ Todos os serviços foram encerrados.")
    sys.exit(0)

def main():
    """Função principal para executar os serviços."""
    clear_screen()
    print("=" * 60)
    print("🚀 INICIANDO SERVIÇOS SMS GATEWAY & UI 🚀")
    print("=" * 60)
    
    # Configurar tratamento de sinal para encerramento limpo
    try:
        if platform.system() != "Windows":
            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)
    except (AttributeError, ValueError):
        pass  # Ignorar erros em sistemas que não suportam sinais
    
    # Iniciar o servidor webhook
    webhook_process = start_webhook()
    
    # Aguardar um pouco para o webhook inicializar
    print("⏳ Aguardando inicialização do webhook...")
    time.sleep(3)
    
    # Iniciar a aplicação Streamlit
    streamlit_process = start_streamlit()
    
    print("\n✅ Todos os serviços foram iniciados!")
    print("-" * 60)
    
    if platform.system() == "Windows":
        print("📋 Instruções para Windows:")
        print("  - Cada serviço está em execução em uma janela separada")
        print("  - Feche as janelas dos serviços quando quiser encerrá-los")
        print("  - Ou pressione Ctrl+C nesta janela para encerrar todos")
    else:
        print("📋 Instruções:")
        print("  - Os logs dos serviços estão em webhook.log e streamlit.log")
        print("  - Pressione Ctrl+C para encerrar todos os serviços")
    
    print("-" * 60)
    
    try:
        # Manter o script principal em execução até Ctrl+C
        while all(process.poll() is None for _, process in processes):
            time.sleep(1)
            
        # Se chegou aqui, um dos processos terminou
        for name, process in processes:
            if process.poll() is not None:
                print(f"⚠️ O serviço {name} foi encerrado inesperadamente.")
        
        # Encerrar os outros processos também
        shutdown_handler()
        
    except KeyboardInterrupt:
        # Encerrar processos ao receber Ctrl+C
        shutdown_handler()

if __name__ == "__main__":
    main()