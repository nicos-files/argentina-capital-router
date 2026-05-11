import matplotlib.pyplot as plt


def plot_equity_curve(df_equity, out_path):
    if df_equity is None or df_equity.empty:
        return
    plt.figure(figsize=(10, 5))
    plt.plot(df_equity["date"], df_equity["capital"], label="Equity", color="blue")
    plt.title("Curva de capital")
    plt.xlabel("Fecha")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
