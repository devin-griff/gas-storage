# Gas Storage

Storage lease valuation: intrinsic LP + rolling-intrinsic Monte Carlo

**Live demo:** https://gas-storage.griffith-pse.com  
**Home:** https://griffith-pse.com

## Run locally

    pip install -r requirements.txt
    streamlit run app.py

## Deployment

Auto-deploys to Fly.io on every push to `main` via
`.github/workflows/deploy.yml`. The `Dockerfile` builds a Python 3.12 image
and installs everything from `requirements.txt`; `fly.toml` configures
auto-stop machines. Custom domain wired through Cloudflare DNS.

- **Machine**: `shared-cpu-1x` · 1 GB RAM · single region (`ord`) · `min_machines_running=0` (auto-stops on idle).
- **Cost ceiling**: ~$3.89/mo if traffic kept the VM awake 24/7. Realistic on idle-heavy demo traffic: well under $1/mo per app. Bandwidth is effectively free under Fly's 100 GB/mo egress allowance.

## Files

- `app.py`: Streamlit UI, storage LP, and Monte Carlo, inline
- `Gas storage.ipynb`: formulation companion notebook
- `requirements.txt`: Python deps
- `favicon.png`: Griffith PSE blackletter G favicon
- `Dockerfile`, `fly.toml`, `.dockerignore`: Fly.io production image config
- `.streamlit/config.toml`: Streamlit defaults baked into the image
- `.github/workflows/deploy.yml`: auto-deploy pipeline

## References

[1] A. Boogert and C. de Jong, "Gas Storage Valuation Using a Monte Carlo
Method," *The Journal of Derivatives*, vol. 15, no. 3, pp. 81-98, 2008.
[PM Research](https://www.pm-research.com/content/iijderiv/15/3/81)

[2] N. Secomandi, "Optimal Commodity Trading with a Capacitated Storage
Asset," *Management Science*, vol. 56, no. 3, pp. 449-467, 2010.
[INFORMS](https://pubsonline.informs.org/doi/10.1287/mnsc.1090.1049)

[3] A. Eydeland and K. Wolyniec, *Energy and Power Risk Management: New
Developments in Modeling, Pricing, and Hedging*. Hoboken: Wiley, 2003.

[4] M. L. Bynum, G. A. Hackebeil, W. E. Hart, C. D. Laird, B. L. Nicholson,
J. D. Siirola, J.-P. Watson, and D. L. Woodruff, *Pyomo: Optimization
Modeling in Python*, 3rd ed. Cham: Springer, 2021.
[Springer](https://link.springer.com/book/10.1007/978-3-030-68928-5)
