# Databricks notebook source
# MAGIC %md
# MAGIC # p05_link_notices_awards: from tender notice to signed contract
# MAGIC
# MAGIC Links each contract to the notices that advertised it (Invitation for Bids, Request for Expression of Interest, Invitation for Prequalification) and to the Contract Award notice that announced it, then derives the procurement timeline of every contract. The timeline table is the training target for the phase-2 delay and risk model.
# MAGIC
# MAGIC | Output | Grain | Key |
# MAGIC |---|---|---|
# MAGIC | `proc_silver.notice_contract_links` | notice x contract, with role (tender / award) and how it was matched | `notice_id, contract_id` |
# MAGIC | `proc_gold.tender_timelines` | contract, with its milestones, durations, context and data-gap flags | `contract_id` |

# COMMAND ----------

# MAGIC %md-sandbox
# MAGIC <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABkAAAAEfCAMAAAAurfo5AAAAwFBMVEX//////9rZ///39/fu7u7v79jx77XY7++17/Lp6enk5OTi4uLk4dfz15Le3t7Z3d7W1tbbyqzHx8fFxcTCwsLBwcHOuZzhnkWa2/OBzvC1tbSFtdasrKyoqKejo6NWqumenp6cnJyznGqampqZmZm1jlaQkI+Li4s+lNbGeiWuVAJ4dG9mZmaUVSc8dqgRaL0VVJqMPQqGJQBrFQEnIiUpCwICNI0AJYIDEDhLAAAnAAAPAAAAAEcAACYAAA8AAABWRdyZAAA6RUlEQVR42u2dCVfiTNOGUdbohzIyGkAdfH1UVgVEcUHJ//9XX1V1d9IJi4AQAe/7zGFNOjEDddFdWyIBQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRAEQRC0TmXevOo6xk02XnJrOWH3qfwjx4UgCILiAUj+3eus6XwHyR84LgRBELRegOR7dfVgr/dZnnen9O3H/LOG5mjm+S5yXAiCIGhjALL36NUX38v1PrDsBEEQBIDECZD8Q3L+jRuYmkAQBK1G+b7nvbYUQM7o8ei1pKz5vjbrL/vJ22fapr4fscReOXM/9D619c70ht5okFMOCNbLfqLpeZ8lQYqM8JCVDWkn7/U8eh5N2UlxjM9p1B3DiX8eDXvD14f+qEwH7cjbcgb6uOEzVHtfv7/s4z8dgiBoBXLJFj8NlUGmxyN+TNOHTN8ra7teZ3s8etYosAEy6Hsj2lzc1e5Q9h3Rvvk3HuepS4Ze78VIGbF13/c39DqRWUNjKHuVOYSKHxEDquOMUefhPimAuGpYPuH8+8e9POFpjD5u6Az3ep48jv4ZEARB0HL8GHr0+5xNNhnkvVZOwCA2WHEh8/ZZovUtstB7d2MzEK/LQBCTTIjg3/kNeRIsYfHuKmaKtkxey4bi/qbt69OWsFyPN0k2o0ta1nnQEapmEP+Wp0552UYfN3SGdGplc4IQBEHQd7XXN5wIfCA0+RDjLObbJdNPNn+S36DhyWLQnmze9Lo8oyCr3xkHSNPzl41oHlA3uNifDBBzTnRfj8Tm+uehANIQLqkTyb+ruKuG17UAEpyhHm1sUAiCIGgp5bXRDjnRm/JDX0y0PCaj292fChDZxN9fuBABiD14/u2jpB9EpwIGIISCklkj24/QzpyHOrumXj3jHc1erpxVCCD6DBV9mkgQgSAIWoWMiTU2/qw/ZEdBXc896PUPtT41etifBRDf6BORSlGAmMlBQrtctKYBxFrKikxSgvNYBiAeAAJB0Pw6LhRoXaVQPKXHlUrFv724+h/d1mpXiURKbg9rtctE4qBWo3cLtdqF3P5NJE7klWKtVkgkTmu1E7k9pgFqtSMaTG7/1WqpROK/Ws2Rx0ke+E6Gr9HtHT+mg/yT4f+ZAx6ZQ53KbUVeocd/5VAVc3sip1CQA9LwV3KoK3l8WasdymNzwKS5HT/shQyvbunvdNRfeFE8InM6KNIwh2cMkEMJwlJe9KPiGbGjIJOAQvGMHdAPf+ViFlNym2TzzBf2pKcAwmFVxeI12fHiKa0TJYvFghjyc3mTLpRTpAOSf+OprfSwf1Qs0l+ibo+Lt8SBY3pMPDjnVwr8QnBAvtXnUUwyoorkufk4NSfCBznhUCuGRvKMAZISgKSKRTrD1BkvjKWKdFeXE+ELe2L9r6pb++IfyUX2L/g/67/gJrjsdJFvrIt/Y/6HD8zHyP9I+f/nFXPwivXB+mudgvrf/p/5fz6QW0c+ZOZQ+uNlDntl/ofVh8yR/+dj+UgVrQ+Zf9hj6+8smL/zn3WoO/0x4r/TfJj8v1B9gBw51KEMfGz+2hPzqS6qx5XKkbk9qVQcuU2Z2yP5fh4UCinYKmgD5NDH8fTfHVnEVrvtyO1BItlutxLymN4lu0XfgnbrDgDRAHk59QHyfz2Orj1ke0tW/S/dFcRjwdY7Q6b7YQ6AsNGfDZCP80OBxoFBx1SAiP0PAaRYlPMwAKEZSfcv3z4UvwRIkZ3oqb/3NEPaEoD8Z/0/xwuQ1GSA3CwCEPX3/G216PFVu01fppt2uyC39PfU5PtJt3yodvvEPK61+LBXV/wz7xAGDYpTNfmA3rX4m38qv3DUDOQIv28SM5L3giUsckuUfR8Ir0a90AqWCYRKWp7w7/hAJjvkJ/pAmhEfiHUe2kOjw3jZM/LVEpYJ4x3Bh74xohkIg0K+pfSN5durm4R8h/lnXruGSwTFJPrwXVwUgYrEwsUOqwFAVOCVAUim/9mSkKYpieIh86xdC2TYO2KrO+EoLJ8EHGKVnO3QN4FSKmp3Mmc0QPZuOSexnkzMAZAET14k1BfaCp1c0KQmdYoLAcXwW6bl4CIsw92mStcTkKiZAueEdPzccMFLo5rkLQfTZyCJ/HCk9hUzrlJJksaQ81IT54HcVlXiCSdy3I5NRBQwkpK3URYKRUubBOehAJLpd4+TPgq/AIg7rGfxH75tqvDyFgStWXetJC7CMsoYv7mfic7/9FrSUD0gy87J6tH6t+Hf9zqLfWQmNLRHxxhypobkln+oTHTv6dnzxiuKyIIUBXElmzoTvTRGGHMeOpFwSKnrJC6R8iVAGp7a+ByflG3SVQvXAFr7D+kWZrpLaq9BZUZeL5Wbwn2mclalvfth3c7ok+Beb1BKzAIIlXD3dC0sw6UAILr+1UPOFM3ynur74/+LsiBVMjW5xmthBeehAJLk8iesj9LXAMk86vDhAWphbdNXG7yHoO1ky6NX3pJZVGcBr88I5XghCILWbpgjToimNz0NMLFcHUdfk4Oj5jtiYwGAaPc7tDU6PMI1gNarA8SMr4Efvahdvm5b+n7zp7w93PnETWYfca/XzSb8AopfHe2pui/umA8EYm2VWlfT3klWfrcQOLQqSWoVtEpxTfaX3OaXopcIgO4cbo2mp1zzI0xAtkt3U9NBkjf/Ln6vLm8wNVvZj5RLXIOVZ4i8bn68Upp7RI1ezufa+A878j8f0DZ3y3RamQ6Qk9Tv1REAsrofKUVcAwj6ZQJAIAiCIAAEAIEgCFq1nEoKAAFA1vpLpIBsIwjaTRXaxwAIALLejxguJQTtpg65yDYAAoCsTyfU9gOCoF1U6r9DAAQAWetvlAqWsCAoASc6AAJBEAQBIAAIBEHQ93TsACAAyDrlHOMaQNCOqvUPAAFA1qkLNJ2BoF1V7QYAAUDWqUsABIJ29vfhKQACgKxTBfQjhKAEnOgACARBEASAACAQBEHf5USlAIAAIGvUyV9cAwhK/LIwLAAESqy3ZxkEQduuf+0kAAKArE81AASCdlYHoSCZdrt1AoAAICtU8QTXAIJ+h9qk1iEAAoBAEATNo4urpA2QdvvuCAABQCAIgr7WabuVDAGk3a4VABBoNZ8uLGFB0E7roEKdQa4qJwFAaCGrBoBAK1DrCtcA2jW53sv+nJvmn+pxnVX+/bM0/9aN+f+GOXTUat/ZAGm3ARAIAIGg7wGk6X2UErsPkPASFi1iYQYCrWQJq4BrAP06gKRvP3J602F3P/HbAHJ3BB8IBEHQcgBxPQOQGLUpAPnvAFFYAAgEQQDIwgCpHSQ2Ow8k0+9mF92n6XUBkB9RBUtY0HYpcz/0vNfzRGKv53XUK2+f5UT6/plefti3ANL0lINc3Z/1PW/0WlIviKpk0z01RvKW964nxc535NlgImKCw+w9ql33emW5e6Tx9njHUTenePGRc5+Vi8XlnVo2QOwtG16Z/6jPBxVuu9egsxrcrwUgtcLGZ6I3vFEVANkWtS9wDaCtml0MvdETIaST9OcRrjfY3yM8PJFNllcmAcT11H78UmPIT57KifzbUCiQeaQXaO+XnBj+e3kyaZJiH0YfhYBjeJFs8rieJ6BQ4wwH+wn18lC/rgy4vWXDG/RpS82yTF+dyxoAklhzLayzXv37m+bfX3IACAACQWtZBxpV5Y5IQKa2an77J9yqzEXECE8CyF4rJ7ZaE8bQocE7JFUsltqbhuZ5Sv7NmxTgax2GlqTKKo4rZwbK66lJV50iv5/ko/E57zUtgIS2bHgee/JdeZ9ee1XnsnUAST969dVvCoBgCQuCViNatqobL8Y+Wd6u/u0f9n5MXMJK6J/31XGAaBQoL4V5ogaf4WRR58IThrpMTco+HGR0YZxaYZNjTvKBqC21u2NPzs2cWgMA4e3uSwAIBEErmoC86bSN/JvYen7W1K4QeXloLS5NAIh+HAGIMdZkwuu+nZ/libcO43qv73SnXkkYn0wpoU/OGmgCQNSW5vB8br5jZ8MA4pz1ae2we86P//To4YtY9uZnKd9j75HDa0/iWXrJMh6qfxisqbR29WgciKfpIWdt6i9p0eaf3VKKaKteTt+/00FuvUE2dBD2sisnWPBk1O0BIBAEJb6Or/JFplfmAJm+MtTi3g55JyIAERM4nAQQgyCx3l8AxDoMQ4x2qfZo8tFQQyjfuKcBktOH70yIwrK2tAFipisbBpD0o3LjfJZTKe2FGtXVT/83T1xLBJA38Sx1BSAP76Pnj1K6p109ZeXdUN6dQTbYVEvG5FEy9J/EABFPEI37UQofxD+8JzubIQGQn1rCOsY1gLYJIJ8mG+5Br1W5aqnJHSpbNQ0gez3Liz4FIPJgNkDsw/DA5PLdz3tdvYIl9oztrAUQcmrUxwFib2kDxN9oowCSbnqvZZ6GnIvNfsimnIZQgWIB6EmaXUvWuhTjhl4+oI3pjp92ab5AbBzQVgfX5bElLKfHMw3nmmc1LgPEYa8UH5bHDR2EnGA8Ezl75wHYU5STJwDIjyjZruAiQNsEkFBsVKb/WW4a093ZN1Z7EkCaEvo7eQnLn4E8fgWQ0GE4/KvJwbv9j2t2ySTERFpLWDl/0ChAQluGAaJ9KRsFEFfPIdjWN9nWEwJk2Ug7H/Jvo3IYIC/Z0O6KA0F4VQQg9LQTbEz70hSlKuPynX0QOmwnGLOhh4QP5McAcoqLACW2KQirnAil23XfNSy6ycQMgOTflGt8ig9kMKcPJHQYxoCe8Xh29FcYILTPYMwHEtoysoRV3zyA0J/gmDw/Zdq1BdeWm2MTwgAJucj54vOO9alO9IasVVkAeZfnajP7IOwE88ekV+pwov/sEhauJLRFIhPfSYZnBMrgalhEANKxsKDMudouH43C+tDM+ChFAZJpl0IAsQ4jGYkdBRLhmnaERADielaMV8I67CSA0I16skkAsScIHKRmAFIylpu95mGAmFzAtHb1lIMdJwGEF70GpdkAkVFtJ1jZHxIAgSBovjxCyaC4LfvVdK2oV1ryEO/2cFT1LTcnCRrndLLhW/y6pGgoS07+EUkhNOkdFkCIPp/laIERfRhNnIRv9dXEhg7IOPEBQkNIArzr2TMQa8sQQAiJPGHZa24WQOpjAJEHXwHEd/V8ARACjfGLT13C0gDxnWDtnFoaA0AgCJqfIJILrs1r3i9n4nGgzquQYY9/z+7LHYXovPT8THT+p70XHkcJmamAyf4e7I8BpOfpsKjxw/DTrp4IdbS7g4d5feZpUpCeYqyoBZDQliGAyHrYhmWiTwTIPDMQ7TfnWjNfAEQhhL0rk5zoNkA+crZvpQSA/KSSNSQSQtulTI8RUt83a1ol8zJnCuzn+2y29xrPYv25wlQ9qQ3zszcalOilutS+4lwCHyAqqNbUwgotYZGpL4eObh2GbH45YdXDogMSJR6y5Nsv2fmNkqwwuAzVwrK2DAMkkeeUiIcN84H4BnqiD2QaQFzl5M5oH0h1diKhctW7dhjvZzUVBgg7wayqJ3pIAOSHlGr/xUWAoBlq/kDh3vX/cvxOFFYn8IuEAWIipHyANLT7mwFCOwahWf6moTq8ghgFkBRj1NPZitZB0n0vyB7xnwAgPwaQIi4CBM2Y8LzVd+ZvabdOlswDefQ+mCBnZK/dISdipO91HogFEB1L5dgzEH5BXD0yX2Bzn76tW5saQnGyutpaAaTxWT12wvMfNSo7wWSUqowvQ1LWOwDyMyqkcA0gaDo/HkNRX1sOkHa79XepTHRZUWI3TpVtv8pEj64uyRSCPESdACBp39XDdj5Iwgw29ac14vfhfEPlA+lxpjqJK5aED+I7wXKS4IhMdAiCNlXuQzKxSwAhhJwuUwtLheOKPadS7J5fCytk22XdadRxgiistHL15PuyBKaqWHVL1qZ6+D/yTtWPwpK6KKLO2EH+iBPsQdaunGvxXaEWFgRBUAwAka5SW9LS1nGDBEO0tN1ApRCFBUG/DCCEkJMt6Yku7ncAZGPltE9wEaAtULJQoGbeyVQqKbcp//HBkUM/hArszHPk1n9M7x7I4wN5fGjdHhf4c18s0m2yWCzI7Ym5tV9PTbl1isVj6/bI3B4Ui4eJxFGx6JjbQ3mFbg/MK4VikU7qpMjxK3Sb1I/HD65eSdVql7Sr3B7UatQB7qRWI09GsVajd0/ltlLjX4J0S6dzUavRiVzWanSof7UaHeq/Wo0OclOrtS1tOEBcqdeuCygCIJuqAwAE+tk58BHb85MK2bnK1R09rrG1S9ZaLY4RbNfMbaHd/o8eVyr0gT0wt2Q0j+X2qMJlpQsVrsxzLLf0mCz2SaVyKLc0fNG6tSz2LwVIa7MBwt53cZV/nqcAkE3+XZfERYB+QqcXN0lZVCE712q3yci2WjUfIHdXVCY6Wamc+rfjM5DGa44f4xO8xBJWYdOXsJwzdpW/PmRTAAgEQeEfLgSKdosocPpX1pWc5DKFea1OhNACALk53BYn+poEgEDQNs8+aslVtEf/LM+97fVTCZddAeTKWVdPdADk18mp4UpC8XehuUnE3UbkEwARgFylluuJDoBAE3TURhgvFLcO1/CzpVEGQL4GyN3xkj3RQw7u+/I3Q3OtqorhgXV++xcK1fUFQAAQCJp7MapBoTlP50nu5SRQSEod3WvuS9jwypzr/KmSx/OSsHyuuniI6n7xXb+PVI5q9EpLD/dZUqZ/zSRweYCkm4PsWgDCkVdP8+QNKoDkl3ewAyCIwoJ+Jz8epco3FcglkDBAuF/HSLfaoM60fXnCkMgPVfEmLmXlShmOpwkAuaftuXNIT5VU+igBIF9X5q2m1gKQubPOFUAy/ToAAkG/T87yu+aHn9TeKXNjtYP9lJ5+6rHX3Ted/5K3MrEYiqfdX8KKAER2pqjhpnQk3Gt6u1i6fbUAyfRfsmsBCFV4n5MIegnLHVUBEAhC+YP55QYmXgAi/c5123PTmImeVINQLdUDfRpA6hpLalQ9GgAycwLSSa0HII/zTm00QAhlOQAk8cPuzANcBCheFdpH3+jO4Zny6gKQzNuorJr5dRLRzn4WMaYBRC9ZNU1GSfO3pJYsDRDq4VQNqvNyFw8qljuQorpN0x2wQ2mAXGv39dyAgRp2yPSCX35tC0DS9+LMygZND1lqdiN7q6K9qt7u50MuePLa1k705rKLaQDIJnyXIWi5D13L+VZL9M9q0gKINxUg4kUfzgZIzjhWjACQr379i6Mi3VOtPVQPWnkp/ybO9TyXP3R195C6AsjDOzegl04i3FGeu4qkjTPLB8gT7yMdp5pqbFmh0h1FVEdE9c5QP6OjLOnOB0AAEOiXilsbsR/EX8LqRJewFECSTV1NaS6AvJoiH+cAyEyZ6oYSA0XWnVpAZdSkRLe9lXYemTZt5Kiug4wA2vjANBOkAonc23zI7c7/1CYsYend2LvFyJDGUT05bMOTZog9DRBaeSwBIIjCgqAFEcLrVmEn+kcpApCGwkxjPoDUf9sXf1mA2I3NZfKR0w2feE7Skd6CdauNYVXAoHahpx3fBzIecuU3pdIV3KVtuqsZQfvWuclU3c4DMc8BEAj6PXKOvh/L2zEA0WG8o3oiDBDjSZ8HILRDFwCZt0quDRBl7AUj+fdXXt2iV3wwOBJXRbvUQ2G6AhAy/p3sRID4C1M8l2kalz1DyvWU19wAhB1iAAgE/S791/ruCEIKBZBEhgjivZYSEYDodw1AtK+dorhUoFYvBBDXm7+sFgCStXrceiojg0w/XXSefGjzT170IYO9Hlqa0jMRcaKzM6uenQCQZuCQejm2vFNd09rWBkgXAPlRHdUcXAQoXt3VvjH5uD8Pz0DcYT0b4kowA6krn3tX+UhU8Fb+fVTlUbwQQGhAicfKtPcBkPkAQiHQ4s8WU06Uzr99lPLvL9mecZz7XnQfIMb+6zDeP+LMmgQQ3yFVT9veKX8qA4AkNseJjjBeKGadVhLfqIqozFYp8IFQijmJipuEfSCuykR/UgVP5BkFbLFrnYJ6Xu9DABHPvBi8KgAyF0DIdg9yfsdZ8mbfcvBu06u98TIVPZCGgs0IQAbZUB4IIcTKBQwA0rVfq9tPOgDIZukEAIG2yvBdP0n6gZ+JnjGLHIP9SBhvnlMGzpO37+L14Gomr2VVOmv0sB/2geiKWpR6sNtXr1X4NkB6CiDaHaEBkubJRIlf9SQnxPjBm5ElLBXAFSQSchTXGEAanpUfaHJMQgQCQDZGBxVEYUE7IFqaKuMqJL4s5946WU0UVkOZbg0QTvDoOgokdZUskhsHCM0eq5FM9IblkvejsN6t/EAdGxx+Aic6BP1eHTlrKbJYxZWdp6FU6zT5HYCowF0dUUXTv1HZNvp+TqHE7zYksNcHCOdvVJ2U4/LG6Xta4/IXpWyA0PrXJ69//eFcEnrxg4/wp50VZ/0rPXF8kLwtmYoOgEDQ9i6kXK5y6vFU3RcfxwcafszZ0rZVWUEmukoQf332OHecnmrX+lvX0TMScjnRP9o4qHHle5o4jPc98MFHEglVlvtQ6BPsU7c89/5MBImEWMKCfp0Zu1jhYBz0qepe4MLO2xO93SosXwtLm/n0vfRPyff1Gpb2det6WA57ml7OqUNU3S6SmL4nArxe8cQhrZ1Zk4opOvLe07ljFd06VwjillMv1+8oZZLYFCd6ChcBileVlTYx+3M/lGJ7uK6zlTwonLR9tWrLV+Ndug3HqoViij+uIgACQbuuw0qt1Y5o+X4g32xIuDIt35kEAFndJwtLWBCU2O3qx+3W5elJ4fgwwMfFNzoSfrMh+cq0/IkAIBC0vQYNs944ddGuFSI+kLvUN1raphqbMQVJP6KlLQT9OqXaf3ER4tONFbOg8HF18K2e6OTW3ogpSH751uwAyMp+DP7DEhYUN0BOcBES8YXJVMJRWJep77W03QUBIKvSaRsAgeJVsoLyOfGp1kraALlIfrcnOgACASAQ9EumexerbSgFgED256uAawBBid2N0z8BQAAQCNqdHy0V9KCJTZdTEr0AEAiCtlFHbUx7Y9NdKwGAACBr00kN1wCKV8cASHxq3QEgAMj6VGnjGkBxL2EhkTA+gFwBIAAIAAJBUGJ1lY8BEGgVco5xDSBod6N4TwEQAASCduhHC5awYtPBtKx/AASCoG1UoX2Ii5D44YAFAARahU7vcA2gRMzVmVDKJD5YHwEgAMj6dNnCNYDiVeovyuf8OKwBEGgV+geAQNAO17pLASAAyBqF1QQISuxumH4SAAFAICiBNsrQ6vK8ABAIgrZRf9sI403EVksRAAFA1qj/wQcCJTZkXR5KxObjBECgVegGxRShmHWEJazYdAWALA4Q5wCKKgmAQBBWGAKA/O/qF2smQC5uoKimtfA5QFIwBP2+FYbkye/WrFXUi4tjKKSTG/SAgzZnCQvXIC7dYYVhcV1UUlBIBQAESqCFAAACASArBcjdP3xeIABkV1UDQACQdQKkhmKKUMwqYAkrPoDg+w2ArBUgN/i8QBAAAgEg8IFAEIQfiAAIAAJhCQsCQAAQAASC7O8nyufEptYVrgEAskaAtE7xeYESaGIGgEAAyOIAaV/g8wJhCWtnAYIwfQBkrQDBlxmCABAIAIEPBIKgEEAucQ0AEAAE2qUlLPjdABAABACBoMQqe1RAqwcIfJwAyBoB4rRP8HmB4tV/qM8UmxAkA4CsEyBH7QI+L2Mq/g9agaZd3gO0EwVAAJCdAMhhC1/mcZ1enULf1QVyoDcBIIiyBEDgA4kbIP/wkfm2TgAQAAQAAUAAEGi1ADkp4iMGgAAguwCQVBIfFwAkZoCgyVFsSgIgAMg6AYKyRABI/ABBjwoABADZCYD8B4AAIHED5PAAH7HYAIKkTQBkjQD5hx+DAAic6AAIBIDAiQ6AACAQAAKAACAAyO4C5B+qH8SlVPsvLgIAsjaAOMhDB0BiBwhKjAMgAMhOAOSijTBeACR2gKC8RnwAQc4NALI2gCRb8KEDILED5BjrqfEBBMuFmw6Q/PtneQXDZPrdbOwzkBsEVAIgcKLvrlBt+9cApOGNqrECJImPFgACgAAg0DoActarxwGQ9PVT2QzzkosTIJV2+xAfFQAkfoAk/0MFaABkxwGSfvRiAciKpi9fAqRWq9EnqVKrUdjV31aLgsMvb07gQAdAfgAgM4zaYQVaStO8SgcACACyaoCc1O4QvQuA/BhADqc3MSvcXEJL6OZ48WsNrREg+XeP9cJubef62fM+H3Lycid9S88GJdlK3nltawac9T1v1JV3ml49c+95XUcP1/ws5Xu0aV29oLbMieNDVE9l3vTRUpl7HvQhGxkSiYQAyK4sYRWS0wHi4MItrkMAZNMAQvZ89PTEcVE0F/FGjJAyA+SjJ08+2Pqnm7zRUL2lnnjKE970um+jp8Apzs893pJnNemG2vKT3naf5TgEkP5QAcSlrZ7o1Y4THhIAAUB234kOgKwYIGhZ/dNLWGTF2bmd7jE0aGLyWhK81FXcFE0p6B0GSMP7KAkc+AlZfmKP4wQA8WhKQW8yeFy1W1OeBEtYrgCEjiDUui5FhgRAABAABAJAtgwg7vCjpNI06AVj7hvewDEYUS/m39Q7hJMOA+MjFFFFMxA1rxmVU+k+b6EHjAKEdh9k/VmQPSQAAoDsCEAqLQAkLoAcAyA/DJCmsd4MAWPuxdi7noq7lRddY/jlrWbE5GuAEDOqATIavEsEIPn3kT/bCA8JgAAgOwKQfwBIbAAptI/xdf5JgLAHxCgCEE0F9WIz2Ezeqk8CCA1WpX317MRVi2IhgLjW1CU8JAACgOwIQO5qAEh8AEHOzU8D5LWtdR4CiD9H0QDxN6unVgUQe0gABADZlSgsBwABQH4PQOrjWRsaIB0bIN0QMOYASIOXwGYCpJtCPxAABE506BsAQbmJn/aBDJyJAOF3sv6LDc8uRDILID4ymhN9IEHEVXhIAAQAAUCghQGCcqk/AxAT+uTaQbQRJ7p6oqKw3r3qfABJ93XwlgRxSWCWFYXVD7IPw0MCIADIbgCkcgeAxAaQEwDkh4opqiQMh43+B5v4P+1sBCAUU/VKzxwBidP0Ps8d3iz3BUAYPOcmsUSIoTJGVKwV5RFyEnr6vhoZEgABQHYCIMlWDQCJESD44v8MQLi2yNOwI7G3Kt+8HgGI1DsJMtF7+knnK4CYBHM91JCfVP1gXS5uwrnug2x4SABkpwBCHy97epl/qjtjH5fID5q5QvFkVyqYkFt7i5llAeK0CgAIALL7/UDyDA4qKJKS6lej7nl0CYvLVpH1f7lWLzrXXHXkiecMswGScoJaWClVzeQ1AEjqT2/ItbBykSEBkF0GSNP7KK0eIGttMbP0ElYSPpA4AZLC1xktbQGQHQeIO7TnCqsCyFpbzCwDkJPLGpzosQKkCIAAIADIzgMkNWnC+m2A/LAP5K7AZXeLlQrZsJN/dxRP2mpdJAGQOAFyCoAAIAAIALKNAGm1uRBTTTpf/q/Nro8UwnhjB0gSX2cABADZQYDUyYP2KX1fOBpDIUO8at1eCCDpe3r75X6sOU2oc0xoVwUQ02Im0oyGt/Nezx3kgQAgEAACgGwrQDzpEMOR4Pm3oS7X/K5C8GyASBTgsy6IZjen4Te4c4xyv9u7aoDoFjOhZjQq6m8o7QYAkN0HSAUAAUAAkJ0ECJtwyib9UJ0pu+pF9nqfvVsA4WJsqgUN55nazWlSLs8p6I1OdFezhOVqgFjNaKjcM+9F29UBkF8BEHybARAAZGd9IH5vsq5VvMb2gbh6hiE+kFBzmpTdiCy0axQgVjOaoMDC2t0kAAgAAoAAIFGRqdpfbA/3qRx6nnl82F/NuSQbL7mVnebPONGb2v53LSxYAPEtfiPUZ8baIj8kFIR3nQgQ1YzmTeebmG5lAMhuA+QCAIkHIJl2FgBZD0DIVg5CC7HU07e8mnOhhf/OlgNETQUayu77ZTa7Y9s1VAFoqzmN9qJ7oa4A0wGiS0H7AkB+BUBawEEcAMm81f1QSXZHalVTzSHf+6Eulpzep5U87D7xdpQ1ng33glI14W85o9xEvkwIyAyPpYyGZS266os/enpQW92WtgAg6dsPPTtojqoRs/+yohnIXu+zvDsA8ZeV7PlF0L9SAGI1p2F/uNTEob3Cu84CyKcZoI0lrF8AkEsAJA6ApHvalTkOkKm/1/LvA4sD/k+7l9wYQLgoSvDeJICEx5oGEHnI27kfpc0HCNu0H/wMbCdASuMACc9A6vaHRvnh3xVASvMBJL4MEQBkAwDyDwCJAyCuWls2APk8Lygd8LevUDih0PlBdmyfUC0KqtlbKPzrm2KKXX8EXnwePZwUzu49Uy7xZfZYPkA6epBjNfwfzgHg4dP9RXvcbglA9u5zvw0gDflk6SUs3y9iL2HVbR+I1ZxG96MRWoR3nQ4QCsIqAyC/CCBXAEgMAEn31NfKB0g5mhQ8/sst/RiaBugNKM6S70OpxE0zfaElh85EgETG8gFSHxv+Uf3SdBcNwlwSIHuqjqS26nsNmpsNKKNtP0+noc1017zxep6U5amPHJWH/CjpSVg10ZBbeqcvGXAJyW8j2978KGU4v63qjz0a3Hpd31tCDmOpM3lugCQZdNnIMT5Lam9ry+A0twAg2vstAFGl/cMAcZr609KwW9DYTWeEFuFdpwPE3w4A+R0A+R8AEgNAguql0wASek3v002NA0R/xW2A5N98a9/UyxVRgETGmg6QFPufVZW8bAwASZrC82Klg4y2/T0ye/qlsriyJVFtsC/G/d4bDQf7DVmgp/gr9g4RJFTZetpN8tsYIH5+mxl76NmTlqanDu51kuLtUAdncAXHeFanxkzivbv74dNc7K9tt1snceeBZHp2Hoirlij/9O2Pz7s3UKkfnAdiN6fRn9Y3+U0R2pU/cs5EgPj9Zm6rAMhvAMhNDThYP0AaeoFq1gwkarEb4VpG0wHiBpW680PeqfHVWDMAopcqJCQzhhlInuNt9x7VNIMz2sRYk2V2lXmWO3rlgWw8Z7QJTNivnbSWsGjHKvOA+XJdMnsxIGi3ZEM2Y7Qyr0IA4cMlb4dMmCRn0NFQskVwjMwbA4QOwG/Sy/XIaS4IEELI35/IRDcASTe98Ux00yBGPjV2cxrVscZ7lR8ooV1p2iL+tgkAEc8756+vv07vNgFkUvWxmbp9KuvCMPJfOHfnFbNfXAC5A0DWDxD6anVTswBycD02Acn0w2taxsI3xpawmsF3VS1ojwEkOtYsgAxV75Hegk2mvuUDyYtdN0BoKGhI+FOTTXZDzRF4YlDSVjzkAxGA0E0n8I4ogHRUkC/F9NJfXFYziaoFkE7gzOBkBxmLpz7BMRRAzJHkPnSaCwOk3a4dxQSQzpms6WVTAUBUpavXergWltpOf2qs5jQpWQF8yJ698WcjtCtt9TEFIKrfzNNDFjOQbwCEQ9Oz6n70RN/veTuvmP1iA0jtDjhYO0DCjko/CktMtV7KfylNdrtHLPz/0cJN3YrCqvqZYqlgwXsMINGxIlFY9TEXS4hK6weImGlaQ7IMujLvvPTHNl2F0tKDqqLIBIAkGsZtEgGI2SuntqyPAYSYWfKfyIPgGAog5k3GUOQ0FwcIIaSAlrYAyET9ue8a19SonrK+3F90XhnbLzaAtG6Ag7UDJP/+JUDIQxv5xEWmJH6crfzACAOka011JgEkOtY0gDh/ep6fl7xYJO+yAFFedPY0+LMDZZnz6te+WrQKwp4NCsYBQree9saHAfIYYGciQPjAe1YGXcc6hkKb2YunJ5HTXAYgtJB1CYAAIHNslunPF9S28ArZ6gByBRzEDxAVxnvs+AG5FJ4bnqLm38ZmEQo6VSdlhfEeRGYgE5ewxsaKhPEejPGJx1gskbjQai+oWoV0zSVeyT39Wa9cD+mGReFNF5XKJTk+Lt9G9NL10HvSav+Pnn2cy2aVW08/uuh7D3zHZcRfLuUdHqHnDfx36TgP6nAPFSP9fuWajkQbvZqDPFjHuH6jk6I3u+ZA3chpVhb+u5UAEABkHoDMWRDmBwFyCRz8AEDGnOjpZtjqj8XRsqu84A7Hixlpr4gVkBUFyNhYE30gah5Uz6aWA0jtsrKYioSuP7Rie853RFSq31oVntHpq7vB9ZAfnQVpM/KMroNIrgjrD/0h6iVyiA/kHd5PQ1a9S8FI53Jb8kcyEOaL9ifIiQkdQ87Mf5NOtx49zQX+YosfLQBkCwFyJt4d/glnAlfcruOHwATvSgQ0e7/53fEOLPn3jniaBiXdjoWdS7yfBD5I4r+Epps1gq7fecVu0aKdVbnU+H6hQTmCJuN3hlk5QNoXwMEmAMSOpZLEkc9SaoIPpKm3Ckdh+dNc9TACkPGxJjvRS2ousiRAllrC0rFWslDEsyd7bSjz9tGT1aKQ53v6EpZ+TTm9o0tYJozXLkwS8YF0Jx0j7AMh1JSjp7nMEtbdMXwgWwiQfNDpREcpOk35ajmcMZO3+6BwCPnoiRcVJnRgoY9XT4WM59SPPgkRH2SlwQpFppO3Q0LT6ZvLjHjq+J1X/BC3jpPu6Qj4cmpsv9CgHALaV0HozuoBkmxXgIP1A+RtHoDYFptKjziTAEIfXO0DCeWB6I8Gx/KP54GMjzUjCitegDRMoJQy08oiG8vcNFkbTdtUB8Y9PwEgCjYTACJphpTwkBgDSLKpwoYttkQBEgRe0X30NBcGyH8HCTjRtxEg6fuy2HAdRx/0SpHKw/a77KMkkDjOxA4sxBTdgaUu38KXnP8b0/9e65A2fwnLNd5T5lP6mnd/UP2/us74fqFBGwpq7neqW04FyEG7CBysPwqr//USVi9kwRtjaRjawkc/aGrjkala4dXHM9HHx5oLIB+5OGYgbJkzj1I9lzPa9iUVQ1lmP5iWvzaSFFKPGHdJ4DCIyHMSuSuhWBMA4pLzKHJwnfnBV0+2Ejd7pr0/DhBynvMJuHJC0dNcECD/nHjyQACQNflAVP179X1xPX3nh87q6vgmmHFiBxbz/W9w3Rh/MSwcnj8RIDR4NEZXf28j+4UG1ebAbvGyOoAUuCs9tO48kN7MPBBaSb/ue3aobbr/UZoMEB0eFa2F5XWpFlZ/Yi2sCWPNAZCmt1gq+nIA2VMNVF+fJdPD9UIp3ns9f67xbqrC2sadtx89f5T8RELZuTMxCouejNhB/nKeCGei8+E4SzHhZ9BVxwHip8JLPkrkNBcCyE0qkQBAttuJblqrcN2Wz2e6o6Spevhdv6/KpA4s/vffVdXHumYdofoVQCYUGtNtVyL7hQbV5iB0lisDSLF9BBz8cCa6XQbXX23tpKYAhD6S8rHzrEDe/NuMarwTxpoLILEkEu7dS65bpq/stMloU5bZ9TMD2QnIrsPQDESSyDkrXHs5ZJvz5GSA+AWLOxZABvdqAD2aOCVLE5awqHT8/XtQCytymvMD5O74G7Ww1BLJlI/XV7SfnsicbrwsXLt/vO7O9NMy6YXLHGfjACJ+8qFGBJewHvDkg4x4aezdevhKTQOI/yVUqJkNkPCXNK0j4McBEh7UfDqa6wBIpZ0CDn64Fpbu8+GEzHd1GkDUIlYYIPqz9DSxH8iEsb4GiPna71pLW7uCb3Nqr6jEBra0TTenZxh/DZDpiczcMisOgHx5nMV70MTuA+FvHbuwu7pPI321KEKlrFawQu8aYz2pA8tkgKgHCwBETcuHMwEiD9YKkEs0JIynGu9nbEWuV6Kx1JEdAYiZUWwfQNwZRP8aINMTmZf5aC41A/nqOIv3oIkbIA2VhaUWqejHfe2N4568bk97Hq13LYCU5pyBvC0GEK5ZkvM3mDYDeVs3QGooxhtPP5BhfasA4i44Adl4gLiy/rRnrzttFUAyszq0NLyXWPslLwOQr39kLdyDJmaAGH+GLivWUDUc2HfGkAi/GyxhjXdg+Y4PJLjurlqvzsztA1kPQNoohRVPR8Lmyza1RE/3BtmdAoiUKuH1BStYd6sA4s5aANoJgCzegyZugLx9WoWNmQ0yuyCQDJzou8ZYT+rAEgZItEiqDrmfHIXVD3I59Fn4AAntFxp0nQA5RBpITD3R04/bNAX50Za265F4OF8f9hNbCZC0Lq+f7w1VqdyGH9fXFUstpXLP/Tznd85RZs/YSJqC6ERmcZVJGrM/TtM0U+YauiPl56bsuDzX4a2P21pVkretLSDH/VHYQeCF6+aMw58W6F/uLYDo40SyolVsgq5+sHAPmrkBQrk3h98HCP0fdJyUQ7l8Yqz5qTXJCL/rG+vJHVgsgGQUYtx3XZKO3zqYlgdimq3cV/XimETAj+8XGnSdALlsH4IGsQAklWlt0RTkduFeDlviA9kULQoQLgapHadPQ8WMEEB0YHFHtTB/ksRjCo7mu5esSWR2VKQzmZpgnOazAoir8qhHOslId+Ka5EaWWGfeJ627gbF73s6L1k1FdIcRA5BnDRA7K9pvFJZNLdODZgGAUPa/820fiL5GT/qvbKg7p6lzLux3fWM9qQNLCCD+RZCZChcvoU5m2SkA8f+nB9m0HwHfzY7vZw+6RoAksYIVG0B2XADIWgHSMH0FaeHbuR6fgfDkI63ySHWeM9kzbiXlqt/HagldpT7XstY42kTRTvTT1mlo68dP0hNySSmYi6YlRAsFA7acabWPnRedfjSZ1tYSljpOKCuaG4Vlg0oKC/egWQgg7fZF6rthvKoDMs3v1BqWXubV9bBC7wbGekIHljBAqLzVuylbpVqw8KxxCkBUs5XXB24hqSLg833ZIrKfPej6AHLYQhAvAAKAbAFAdF6nv9Q9toSV9Tsa62wzHYnj9HQv21AeWjCOMlE0NxFrqDJeTZflt2jaminJIxZQp7CZ3GsratWEHjUmAcTKim5q/4CeXi3cg2ZBgHAJZLS0XR1AkpV2CwtYAAgAsvkA4dpGWbXUXZ0BEFmO179vjeFuBABJ900ljGAcZdhVYpAhgAbI+JKSjvxRh3CDwXzfhSoK1fN7ykwDiGRF++ObB4v2oFkYIOQLKQIgqwBI6rhSa6MQLwACgGwVQHhF/eV8KkDkh/10gDBgRg/hcZRh98OqZPIQaVE73nVCNg9yWQMHveRF+zSaDhBZTgk1ClumgOdJqzaf7EYsAMhSALEvZ0t64NROsXwFgAAgWwUQivJ5V+2PJwJElq1mAEStlHNwlT9OBCAaDZMB4uen6a1ejVGuh/Ki/cG+Bohv1ksAyPYA5OZf5bSQxJcYAAFAtg0g7JR9V8H9S8xAxAmrg6v0OIvMQLiF5RhmxvOi/eS5LwES4cXCAFl8CevfCQCy2oZSEAACgGw8QHpWqqAY6Mk+kLeZPpBUuPWlMvTTfSCTlrAGWR8gDdvlbedFZ0Ldb6YDxN8uNoBcwIkOgAAgAMivjcIaq5CnwqaMWXZVFNZMgAQFldSKlInC6gRzjKkAMT2JVBTWu/W2nRftmJP9AiBOtGXAoj1oFgRIJfmDPdEBEAgAAUB+CiCmnRg7C3Sslcnf8/NAHJV4PAMgDcr5TvM0IhhHG3Z3KAke9zoPZApAaImMc0scAQnZ/08u//yn7Ufu6rxobrmVM9MmR0+exgFi+us51/XletAsBJD/nFX1AwFAIAAEANnGTPSGykN+yao0cEpEvvcz0Z/8TPRpAOG2MZxtXrXGMalqDeUDH1VTMwDiu8pVJnpPP+noTGg/L9rPjNflN0bViQDhLEfVKKy0VA+aBQDyL7V8KROnUf3WV8NfH5x7wXL1rVMAEAAEAPnFADGJyfemmJWEzVJMrvKBfJTurVpY0wDinPWHKnzXGsfkOp8xDnQtrKkASXEhq9HLtTqEc/3kd6EJ50WfmZZbWfVkCkBSulFYbrkeNDEVU2x85OIFyHwtWoIYBJ6eup4lmVOas3Zfsqlo8586AAKAACC/CCCLl6rdPi3cgyYegOTfv3nl5wXIWa++SIuWLwDS0Ad1ejK/CwEk/1YFQAAQAOQXASTTH2R/pC+MpfqG9aCJBSDp3kcpFoCETHxqUYAcFEhU87fD98dOpCVIdPTGok3EABAABADZZoCk3B/paZm3c/DOU5vVgyYWgLhB2bBNBkh0CHqoXnQV+MOj598XvNYACAACgGw1QFKNQXanP0Gb2dLW0d4aR3qfiJfJ1IrUVXjFvSTdZp6k+C27cmgqILvxTq/tt1C8c6ghStCFRRd2kR6FOlpat2/JBd6ic2degHDARFV5m2QqEgZI+nHBnyMACAACgGw3QNK35Z3+BC3egyYOgOgVIP4hP9ItUnTtR4f6bhnC5FUvENOa4+F99PxRUtFo/HIIIHZDFKsLC1v80dMTjWBatEjI27PqluJaB5gLIK7uQMKtWTjHMzK/aSwY8AaAACAAyHYDBPoJgJjcyQxnuziqXnBTrD9Z/I5fgPheNeWS6OZHaadyYPoHcpsWGyBWQ5RQF5bAxKuANV0d5uBaNpQKZmfvtif8C4C8vqnS+nRfGgOIu2DOJgACgAAgAAgAsihAwtnxavJhup7oO39pUdWx9+uWZXTP20x4CStoiBLuwhIFiNUdxS+Qb9t9u5jxOECa3kOTD9vwHnp8PwaQURkAAUAAEAAEAFknQJohgEgfE4WRdP/zme7UK3ZBF99UG1/JJICohiihCmQRgNiVwvJv2j9kmnh9CRB2xLh0Npn+Z6mhsVYPp5rUAZAfBMhlEQqpAoAAILsMEMnCJOeFbhrPMw+efJBJL6kkDvJQDDVAqjYrJgIkXI5YUBMBiF2r2A2nePhLWOcF0YQlLB4iQ2tYHG4lcWQAyGYB5AaKCgABQHYXIFKrRXvRyWf+kaMFIk74UytYXFjGe3r2QgAxmRhfA0QezATIpx9LnZvLB0Klb7iqcrUhh3nJASAQBIBAPwQQcldIDK0K6qU1rNobWWVaJFIrWOQG5xDeRgQgg5XNQCa4vGcCRGKL+fRo4MxbaHQABIIAEChOgBjng84KaXgmoFdVIe6bl8NLWMquTwXIVz6QamDuJ7i8ZwJEzoRPb6AL6gMgEASAQLGH8SqAvCsbrQFC9tdUR+Y8dVOQMgwQ0zBlKkDCXVj8UKtIVxXeoG8ngMwBkHRP+2r0XWcCQKoACAQBIABIDHkgKp+QUzo62qJ3LDvMTx1qkzLU7uqqseK8sMVtWiYDJNyFJaWSTHwe6W4p6du6ySihx9X5AKKZRb6akq7GwpBSLvdjx0pvAUAgCAABQNYFEDN9kH4p/E8F1OpqhE5TVzVRieJPnnKGV/2sEeV4nwaQUBcWPhTlrXf8CQ0Nqrql5NRjdtJbXYRnAUS3j0n3B45+n4MArDguJBJCEAACgKy9mKKphcXtV17O0/dDtYalswd1PayUK+1Y0rfvXbutSfqecjVer96mAsTuwkKDMnBoKmNWxFT9q27JFM3ynh6y881AdIt6akFpskciAEEpEwgCQACQ9VfjHXZ378rN13EEAIEgAAQA+WY/kFxq93p3dR0ABIIAEABk7R0Jq6lfXzofAIEgAAQAWaInuvuS27kJCFraQhAAAoDEAJCUu2tTkPzCfxAAAkEACACyDEAgAASCABAABAABQCAIAIEAEAAEgn4rQI6g7+oUAAFAIOg3AgT9Y1YhAAQAgaDfpxTmD6sQAAKAQBAExSQABACBIAgCQAAQCIIgAAQAgSAIAkAAEAiCIAAEAkAgCIIAEAAEgiAIAAFAIAiCABAABIIgCAABQCAIggAQCACBIAgCQAAQCIIgAAQAgSAIAkAAEAiCIAAEAIEgCPoNAPkHLSEABIKgX6+Dv9BScvDZgSAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgiAIgrZb/w/QVMrcPvd1oAAAAABJRU5ErkJggg==" alt="tender_timeline diagram" style="max-width:100%; width:1076px"/>
# MAGIC

# COMMAND ----------

# MAGIC %md
# MAGIC Match tiers, strongest first, always **within the same project**:
# MAGIC
# MAGIC | Tier | Rule |
# MAGIC |---|---|
# MAGIC | `exact_reference` | same reference after removing case, spaces and punctuation |
# MAGIC | `step_activity_id` | same STEP activity id (the 6-digit number in `MZ-MISAU-458432-GO-RFB`) |
# MAGIC | `reference_variant` | one reference is the other plus 1-3 letters (lot or re-issue marker: `EMCRP/G-06A`) |
# MAGIC | `description` | contract has no STEP id; same category; notice 0-3 years before signing; description similarity >= 0.8 and clearly the best candidate |
# MAGIC
# MAGIC Award notices are additionally checked against the **awarded supplier ids** printed in the notice.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Key design decisions
# MAGIC
# MAGIC | Decision | Rationale | Evidence |
# MAGIC |---|---|---|
# MAGIC | Both exact tiers kept (project + reference, and STEP activity id); links where the notice is published after signing are stored, flagged, and never used for durations | A notice after signing indicates a reference re-used for a later round, not the tender of this contract | Exact project + reference matches found tender notices for about 61,500 contracts; the STEP id added only about 2,300 more; about 6,000 links had the notice published after signing |
# MAGIC | The similarity ratio replaced by a structural rule: references must be equal after deleting one block of 1-3 letters (never digits) from the longer one, implemented as an equi-join on generated deletion keys | Ratio >= 0.9 also matched different packages one character apart; the rule needs no pairwise comparison | Lot markers ("17B/W/DNAAS/2018" for tender "17/W/DNAAS/2018") versus false matches ("TCP/CON/QCBS/B1/G" vs ".../B1/D", "ENU-02-22" vs "ENU-03-22") |
# MAGIC | Description matching only for contracts without a STEP id, with >= 0.8 similarity and a clear margin over the second-best notice; the tier is measured separately in the agent audit | Descriptions are the only bridge when the contract reference is the borrower's own number, but they confuse near-identical packages | Even at >= 0.9, wrong-package matches occurred ("Civil Work Package (CWP) 7" vs "CWP 8", "Fish Landing in Brgy. Taruk" vs "Brgy. Tapian"); bridging matches read correctly ("Audit externe des comptes du projet PRAPS-II NE ...") |
# MAGIC | An award link is kept when the notice's awarded supplier id is one of the contract's suppliers (confirmed), or when the pair is one-to-one and the notice names no awardee | One reference is shared by all lots and call-offs of a tender | Reference-only matching produced about 980,000 award-notice/contract pairs (section 3); one reference appears on 188 contracts; the confirmed share among one-to-one pairs with a named awardee is the automatic precision check |
# MAGIC | Coverage reported per competition level; the phase 2 timeline model to be trained on openly competed contracts | Most contracts are never publicly advertised | Request for Quotations, direct selection and individual consultants make up about 80% of contracts |
# MAGIC
# MAGIC Full reasoning: docs/decision_log.md

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC
# MAGIC **What:** libraries, shared helpers, tier constants and the audit label file.
# MAGIC
# MAGIC **Why:** the reference rules are the tested functions in `proc_intel.references`, applied here as UDFs.

# COMMAND ----------

# MAGIC %pip install -q rapidfuzz unidecode

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ./proc_common

# COMMAND ----------

import json

import numpy as np
from pyspark.sql import Window
from pyspark.sql.types import ArrayType, StringType
from sklearn.feature_extraction.text import TfidfVectorizer

from proc_intel.references import TIER_EXACT, TIER_STEP, TIER_VARIANT, variant_keys
from proc_intel.similarity import wilson_interval

TIER_DESCRIPTION = "description"
# lower = stronger evidence; used to keep the best tier when one pair is found by several joins
TIER_ORDER = {TIER_EXACT: 1, TIER_STEP: 2, TIER_VARIANT: 3, TIER_DESCRIPTION: 4}
TENDER_TYPES = ["Invitation for Bids", "Request for Expression of Interest", "Invitation for Prequalification"]
# 0.9 still matched sibling packages ("CWP 7" vs "CWP 8"), so a looser floor plus a clear margin over the runner-up
# works better
DESCRIPTION_MIN = 0.80
DESCRIPTION_MARGIN = 0.10
MAX_TENDER_DAYS = 3 * 365          # a tender notice older than this before signing is not the same round
AUDIT_PATH = os.path.join(os.path.dirname(SRC_DIR), "data", "tender_link_audit.csv")
# more labels for the weaker tiers, where the precision is actually in doubt
AUDIT_PER_TIER = {TIER_EXACT: 15, TIER_STEP: 10, TIER_VARIANT: 8, TIER_DESCRIPTION: 12}
variant_keys_udf = as_udf(variant_keys, ArrayType(StringType()))

contracts = spark.table(f"{SILVER}.contracts").join(
    spark.table(f"{SILVER}.dim_procurement_method").select(F.col("method_name").alias("procurement_method_name"),
                                                            "competition"), "procurement_method_name", "left")
notices = spark.table(f"{SILVER}.notices")
c_keys = contracts.select("contract_id", "project_id", "reference_norm", "step_activity_id", "signing_date")
n_keys = notices.select("notice_id", "notice_type", "project_id", "reference_norm", "step_activity_id", "notice_date")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Reference tiers (exact, STEP id, variant)
# MAGIC
# MAGIC **What:** three equi-joins within the same project:
# MAGIC - on the normalised reference;
# MAGIC - on the STEP activity id;
# MAGIC - on deletion keys: each reference's "minus one block of 1-3 letters" versions joined to the other side's normalised reference, in both directions.
# MAGIC
# MAGIC Each (notice, contract) pair keeps its strongest tier.
# MAGIC
# MAGIC **Why:** joins scale to 283k contracts x 380k notices without comparing every pair.

# COMMAND ----------

# every tier joins inside the same project: references like "GO-01" repeat across projects
exact = (c_keys.join(n_keys, ["project_id", "reference_norm"])
         .select("notice_id", "contract_id", F.lit(TIER_EXACT).alias("match_tier")))
step = (c_keys.filter("step_activity_id IS NOT NULL").join(n_keys, ["project_id", "step_activity_id"])
        .select("notice_id", "contract_id", F.lit(TIER_STEP).alias("match_tier")))
c_var = c_keys.select("contract_id", "project_id", F.explode(variant_keys_udf("reference_norm")).alias("key"))
n_var = n_keys.select("notice_id", "project_id", F.explode(variant_keys_udf("reference_norm")).alias("key"))
# both directions: either side can carry the extra lot / re-issue letters (e.g. "17B/W/..." vs "17/W/...")
variant = (c_var.join(n_keys.withColumnRenamed("reference_norm", "key"), ["project_id", "key"])
           .select("notice_id", "contract_id")
           .union(n_var.join(c_keys.withColumnRenamed("reference_norm", "key"), ["project_id", "key"])
                  .select("notice_id", "contract_id"))
           .withColumn("match_tier", F.lit(TIER_VARIANT)))
# two different STEP ids are never the same tender, whatever the rest of the string says
variant = (variant.join(c_keys.select("contract_id", F.col("step_activity_id").alias("c_step")), "contract_id")
           .join(n_keys.select("notice_id", F.col("step_activity_id").alias("n_step")), "notice_id")
           .filter("c_step IS NULL OR n_step IS NULL OR c_step = n_step").drop("c_step", "n_step"))

tier_rank = F.create_map(*[x for k, v in TIER_ORDER.items() for x in (F.lit(k), F.lit(v))])
reference_links = (exact.union(step).union(variant)
                   .withColumn("_rank", tier_rank[F.col("match_tier")])
                   .withColumn("_rn", F.row_number().over(Window.partitionBy("notice_id", "contract_id").orderBy("_rank")))
                   .filter("_rn = 1").drop("_rank", "_rn")
                   .join(n_keys.select("notice_id", "notice_type", "notice_date"), "notice_id")
                   .join(c_keys.select("contract_id", "signing_date"), "contract_id")
                   .withColumn("link_role", F.when(F.col("notice_type").isin(TENDER_TYPES), "tender")
                               .when(F.col("notice_type") == "Contract Award", "award"))
                   # other notice types (general procurement notices, ...) do not advertise or award a single contract
                   .filter("link_role IS NOT NULL")
                   .cache())
display(reference_links.groupBy("link_role", "match_tier").agg(F.count("*").alias("links"),
                                                               F.countDistinct("contract_id").alias("contracts"),
                                                               F.countDistinct("notice_id").alias("notices"))
        .orderBy("link_role", "match_tier"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Description tier for contracts without a STEP reference
# MAGIC
# MAGIC **What:** for openly competed contracts that have no STEP id and no tender link yet, the candidate tender notices of the same project and category published 0-3 years before signing are scored by TF-IDF cosine of the descriptions (words and word pairs). The best candidate is accepted if it scores >= 0.8 and beats the second-best by >= 0.1.
# MAGIC
# MAGIC **Why:** these contracts carry the borrower's own contract number, so the reference cannot match; the guard against near-identical sibling packages is the margin and the restriction to contracts without a STEP id (Step 3).

# COMMAND ----------

# a notice published after signing is a reused reference, not this contract's tender
tender_linked = reference_links.filter("link_role = 'tender' AND notice_date <= signing_date").select("contract_id").distinct()
# only contracts without a STEP id: with one, a missing reference match is a real gap and descriptions mostly find
# siblings
open_unlinked = (contracts.filter("competition = 'open' AND step_activity_id IS NULL")
                 .join(tender_linked, "contract_id", "left_anti")
                 .select("contract_id", "project_id", "procurement_category_code", "signing_date", "contract_description"))
tender_notices = notices.filter(F.col("notice_type").isin(TENDER_TYPES)).select(
    "notice_id", "project_id", "procurement_category_code", "notice_date", "bid_description")
candidates = (open_unlinked.join(tender_notices, ["project_id", "procurement_category_code"])
              .filter(F.datediff("signing_date", "notice_date").between(0, MAX_TENDER_DAYS))
              .filter("contract_description IS NOT NULL AND bid_description IS NOT NULL")
              .select("contract_id", "notice_id", "contract_description", "bid_description")
              # candidate set is small after the project/category/date filters, so the TF-IDF scoring runs on the driver
              .toPandas())
vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode")
# fit on distinct texts so a description repeated across many candidate pairs does not skew the idf weights
vectorizer.fit(pd.concat([candidates["contract_description"], candidates["bid_description"]]).drop_duplicates())
a = vectorizer.transform(candidates["contract_description"])
b = vectorizer.transform(candidates["bid_description"])
# row-wise dot product of L2-normalised vectors = cosine for each (contract, notice) pair, without a full matrix
candidates["description_similarity"] = np.asarray(a.multiply(b).sum(axis=1)).ravel()
ranked = candidates.sort_values(["contract_id", "description_similarity"], ascending=[True, False])
ranked["rank"] = ranked.groupby("contract_id").cumcount()
second = ranked[ranked["rank"] == 1].set_index("contract_id")["description_similarity"]
best = ranked[ranked["rank"] == 0].set_index("contract_id")
# a contract with a single candidate gets the full score as margin
best["margin"] = best["description_similarity"] - second.reindex(best.index).fillna(0.0)
accepted = best[(best["description_similarity"] >= DESCRIPTION_MIN) & (best["margin"] >= DESCRIPTION_MARGIN)].reset_index()
print(f"open contracts without STEP id or tender link: {open_unlinked.count():,} | with a candidate: {best.shape[0]:,} | "
      f"accepted: {len(accepted):,}")
description_links = (spark.createDataFrame(accepted[["notice_id", "contract_id", "description_similarity"]])
                     .withColumn("match_tier", F.lit(TIER_DESCRIPTION))
                     .join(n_keys.select("notice_id", "notice_type", "notice_date"), "notice_id")
                     .join(c_keys.select("contract_id", "signing_date"), "contract_id")
                     .withColumn("link_role", F.lit("tender")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Award links confirmed by supplier id
# MAGIC
# MAGIC **What:** for each reference-matched award link, checks whether a firm the notice lists as **awarded** is a supplier of the contract. A link is kept if confirmed, or if the notice and the contract are linked only to each other (one-to-one) and the notice names no awarded firm to contradict it. Prints the confirmation rate where the notice names an awarded firm.
# MAGIC
# MAGIC **Why:** shared references make award links many-to-many; the supplier id printed in the notice is independent evidence that picks the right lot. The confirmation rate on one-to-one pairs is a precision estimate for reference matching in general.

# COMMAND ----------

awarded = spark.table(f"{SILVER}.notice_bidders").filter("role = 'awarded'").select("notice_id", "supplier_id")
cs_ids = spark.table(f"{SILVER}.contract_suppliers").select("contract_id", "supplier_id")
award_ref = reference_links.filter("link_role = 'award'")
# the awarded firm's id in the notice HTML must be one of the contract's suppliers: independent of the reference text
confirmed = (award_ref.join(awarded, "notice_id").join(cs_ids, ["contract_id", "supplier_id"])
             .select("notice_id", "contract_id").distinct().withColumn("supplier_confirmed", F.lit(True)))
named = awarded.select("notice_id").distinct().withColumn("notice_names_awardee", F.lit(True))
degree_n = award_ref.groupBy("notice_id").agg(F.count("*").alias("n_contracts_for_notice"))
degree_c = award_ref.groupBy("contract_id").agg(F.count("*").alias("n_notices_for_contract"))
award_scored = (award_ref.join(confirmed, ["notice_id", "contract_id"], "left")
                .join(named, "notice_id", "left").join(degree_n, "notice_id").join(degree_c, "contract_id")
                .fillna(False, ["supplier_confirmed", "notice_names_awardee"])
                .withColumn("one_to_one", (F.col("n_contracts_for_notice") == 1) & (F.col("n_notices_for_contract") == 1)))
one_to_one_named = award_scored.filter("one_to_one AND notice_names_awardee")
rate = one_to_one_named.agg(F.avg(F.col("supplier_confirmed").cast("int"))).first()[0]
print(f"award links by reference: {award_ref.count():,} | one-to-one pairs whose notice names an awardee: "
      f"{one_to_one_named.count():,}, supplier confirmed in {rate:.1%}")
# one-to-one pairs whose notice names a different awardee are dropped: the id contradicts the reference
award_links = award_scored.filter("supplier_confirmed OR (one_to_one AND NOT notice_names_awardee)").select(
    "notice_id", "contract_id", "match_tier", "notice_type", "notice_date", "signing_date", "link_role", "supplier_confirmed")
display(award_scored.groupBy("one_to_one", "notice_names_awardee", "supplier_confirmed").count()
        .orderBy("one_to_one", "notice_names_awardee", "supplier_confirmed"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. `notice_contract_links`
# MAGIC
# MAGIC **What:** all tender links (reference and description tiers) and the kept award links in one bridge table, with the tier, the description similarity where used, supplier confirmation for award links, and whether the notice precedes the signing.
# MAGIC
# MAGIC **Why:** one bridge serves the timeline below and the knowledge graph (`notice -> contract` edges), and the tier column lets any consumer choose its own precision level.

# COMMAND ----------

tender_links = (reference_links.filter("link_role = 'tender'")
                .withColumn("description_similarity", F.lit(None).cast("double"))
                .unionByName(description_links)
                .withColumn("supplier_confirmed", F.lit(None).cast("boolean")))
links = (tender_links.unionByName(award_links.withColumn("description_similarity", F.lit(None).cast("double")))
         .withColumn("days_notice_to_signing", F.datediff("signing_date", "notice_date"))
         # links with the notice after signing are kept for the graph but flagged, and never used for durations
         .withColumn("notice_before_signing", F.col("days_notice_to_signing") >= 0)
         .select("notice_id", "contract_id", "link_role", "match_tier", "description_similarity", "supplier_confirmed",
                 "notice_before_signing", "days_notice_to_signing"))
n_links = publish_table(
    links, f"{SILVER}.notice_contract_links",
    "Bridge between procurement notices and contracts. Grain: one row per notice x contract. Tender links: the "
    "notice advertised the contract (several lots can share one notice). Award links: the Contract Award notice "
    "of the contract, kept when confirmed by awarded supplier id or one-to-one.",
    {"notice_id": "PK, FK notices", "contract_id": "PK, FK contracts",
     "link_role": "tender (IFB / REOI / prequalification) or award (Contract Award notice)",
     "match_tier": "exact_reference, step_activity_id, reference_variant or description (tender only)",
     "description_similarity": "TF-IDF cosine of the descriptions (description tier only)",
     "supplier_confirmed": "Award links: an awarded supplier id in the notice is a supplier of the contract",
     "notice_before_signing": "Notice date on or before the signing date (tender links: false means a re-used reference; award notices normally follow signing)",
     "days_notice_to_signing": "Signing date minus notice date, in days"},
    primary_key=["notice_id", "contract_id"])
add_foreign_key(f"{SILVER}.notice_contract_links", ["notice_id"], f"{SILVER}.notices", ["notice_id"])
add_foreign_key(f"{SILVER}.notice_contract_links", ["contract_id"], f"{SILVER}.contracts", ["contract_id"])
L = spark.table(f"{SILVER}.notice_contract_links")
display(L.groupBy("link_role", "match_tier").agg(F.count("*").alias("links"), F.countDistinct("contract_id").alias("contracts"),
                                                 F.round(F.avg(F.col("notice_before_signing").cast("int")), 3).alias("share_before_signing"))
        .orderBy("link_role", "match_tier"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Agent audit of tender links
# MAGIC
# MAGIC **What:** a reproducible sample per tier (ordered by a hash of the pair) with both descriptions side by side, labelled by an AI agent during the build (agent reference labels) in `data/tender_link_audit.csv` (1 = this notice advertised this contract, or the tender of which it is a lot). Prints the share correct per tier with a Wilson interval.
# MAGIC
# MAGIC **Why:** there is no ground truth for tender links; reading pairs is the only direct check, and doing it per tier shows which tiers can be trusted for the timeline.

# COMMAND ----------

sample = (L.filter("link_role = 'tender' AND notice_before_signing")
          .join(notices.select("notice_id", "bid_reference", "bid_description"), "notice_id")
          .join(contracts.select("contract_id", "borrower_reference", "contract_description"), "contract_id")
          # hash order: a sample that looks random but is the same on every run, so the saved labels still line up
          .withColumn("audit_order", F.sha1(F.concat_ws("#", "notice_id", "contract_id")))
          .withColumn("rn", F.row_number().over(Window.partitionBy("match_tier").orderBy("audit_order")))
          .toPandas())
sample = sample[sample["rn"] <= sample["match_tier"].map(AUDIT_PER_TIER)].sort_values(["match_tier", "rn"])
for col in ["contract_description", "bid_description"]:
    sample[col] = sample[col].str.replace(r"\s+", " ", regex=True).str.slice(0, 160)
if os.path.exists(AUDIT_PATH):
    audit = pd.read_csv(AUDIT_PATH, dtype={"contract_id": str})
    judged = sample.merge(audit[["notice_id", "contract_id", "label_correct", "note"]], on=["notice_id", "contract_id"], how="left")
    rows = []
    for tier, grp in judged.groupby("match_tier"):
        grp = grp[grp["label_correct"].notna()]
        ok = int(grp["label_correct"].sum())
        low, high = wilson_interval(ok, len(grp))
        rows.append({"match_tier": tier, "labelled": len(grp), "correct": ok,
                     "share_correct": round(ok / len(grp), 3) if len(grp) else None,
                     "ci_low": round(low, 2), "ci_high": round(high, 2)})
    display(pd.DataFrame(rows))
    display(judged[["match_tier", "borrower_reference", "bid_reference", "contract_description", "bid_description",
                    "label_correct", "note"]])
else:
    display(sample[["match_tier", "notice_id", "contract_id", "borrower_reference", "bid_reference",
                    "contract_description", "bid_description", "description_similarity"]])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. `proc_gold.tender_timelines`
# MAGIC
# MAGIC **What:** one row per contract with:
# MAGIC - milestones: first tender notice date (earliest linked tender notice before signing), its bid deadline, the award-notification date from the linked award notice, and the signing date;
# MAGIC - durations in days: notice -> deadline (advertising), deadline -> signing (evaluation to signature), notice -> signing (total);
# MAGIC - context: method, competition level, category, review type, amount, country, project, the number of tender notices (a re-advertisement signal), the number of firms named in the award notice, and the borrower's governance scores (WGI) for the year **before** signing, joined from the outcome project's `silver.country_year`; the project's outcome-model risk band;
# MAGIC - `is_timed` and `timing_gap`, which say why a contract has no measured duration.
# MAGIC
# MAGIC **Why:** this is the phase-2 modelling table. Indicators come from the year before signing so a model never sees information from after the event; implausible durations (> 3 years, deadline after signing) are flagged rather than silently dropped.

# COMMAND ----------

tender_first = (L.filter("link_role = 'tender' AND notice_before_signing")
                .join(notices.select("notice_id", "notice_type", "notice_date", "submission_deadline"), "notice_id")
                .withColumn("_rank", tier_rank[F.col("match_tier")])
                # earliest notice first (the original advertisement; later ones are re-advertisements), strongest tier
                # on ties
                .withColumn("_rn", F.row_number().over(Window.partitionBy("contract_id").orderBy("notice_date", "_rank")))
                .groupBy("contract_id").agg(
                    F.min(F.when(F.col("_rn") == 1, F.col("notice_id"))).alias("tender_notice_id"),
                    F.min(F.when(F.col("_rn") == 1, F.col("notice_type"))).alias("tender_notice_type"),
                    F.min(F.when(F.col("_rn") == 1, F.col("match_tier"))).alias("tender_match_tier"),
                    F.min("notice_date").alias("tender_notice_date"),
                    F.min(F.when(F.col("_rn") == 1, F.col("submission_deadline"))).alias("submission_deadline"),
                    F.countDistinct("notice_id").alias("n_tender_notices")))
award_first = (L.filter("link_role = 'award'")
               .join(notices.select("notice_id", "notice_date", "award_notification_date", "n_named_firms"), "notice_id")
               .groupBy("contract_id").agg(F.min("award_notification_date").alias("award_notification_date"),
                                           F.min("notice_date").alias("award_notice_date"),
                                           F.max("n_named_firms").alias("n_named_firms_in_award_notice")))
# leakage guard: year + 1 means a contract signed in year Y gets the indicators of Y-1, already published at signing
wgi = spark.table(COUNTRY_YEAR).select(
    F.col("country_iso2").alias("borrower_country_code"), (F.col("year") + 1).alias("signing_year"),
    "wgi_gov_effectiveness", "wgi_control_corruption", "wgi_rule_of_law", "wgi_regulatory_quality", "log_gdp_pc")
projects = spark.table(f"{SILVER}.dim_project").select("project_id", "region", "major_sector", "outcome_risk_band")

timelines = (contracts
    .select("contract_id", "project_id", "borrower_country_code", "procurement_method_name", "competition",
            "procurement_category_code", "review_type", "contract_amount_usd", "is_joint_venture", "signing_date",
            F.year("signing_date").alias("signing_year"), "fiscal_year")
    .join(tender_first, "contract_id", "left").join(award_first, "contract_id", "left")
    .join(wgi, ["borrower_country_code", "signing_year"], "left").join(projects, "project_id", "left")
    .withColumn("days_notice_to_deadline", F.datediff("submission_deadline", "tender_notice_date"))
    .withColumn("days_deadline_to_signing", F.datediff("signing_date", "submission_deadline"))
    .withColumn("days_notice_to_signing", F.datediff("signing_date", "tender_notice_date"))
    .withColumn("days_award_notice_to_signing", F.datediff("signing_date", "award_notification_date"))
    # implausible durations are labelled, not dropped, so the reason stays visible in the gold table
    .withColumn("timing_gap", F.when(F.col("tender_notice_date").isNull(),
                                     F.when(F.col("competition") == "open", "open method, no tender notice linked")
                                     .otherwise("method not normally advertised"))
                .when(F.col("days_notice_to_signing") > MAX_TENDER_DAYS, "notice more than 3 years before signing")
                .when(F.col("days_deadline_to_signing") < 0, "bid deadline after signing")
                .when(F.col("days_notice_to_deadline") < 0, "bid deadline before notice"))
    .withColumn("is_timed", F.col("timing_gap").isNull()))
n_timelines = publish_table(
    timelines, f"{GOLD}.tender_timelines",
    "Procurement timeline per contract: tender notice, bid deadline, award notification and signing, with durations, "
    "context and data-gap flags. Grain: one row per contract. Target table for the phase-2 delay/risk model.",
    {"contract_id": "PK, FK proc_silver.contracts", "project_id": "FK proc_silver.dim_project",
     "borrower_country_code": "FK proc_silver.dim_country", "procurement_method_name": "Procurement method",
     "competition": "open / limited / direct / other", "procurement_category_code": "CW / GO / CS / NC",
     "review_type": "Prior or Post review", "contract_amount_usd": "Contract value (US$, once per contract)",
     "is_joint_venture": "More than one supplier", "signing_date": "Contract signing date",
     "signing_year": "Calendar year of signing", "fiscal_year": "World Bank fiscal year of signing",
     "tender_notice_id": "Earliest tender notice linked before signing",
     "tender_notice_type": "Its type (IFB / REOI / prequalification)", "tender_match_tier": "How it was linked",
     "tender_notice_date": "Date of the earliest linked tender notice",
     "submission_deadline": "Bid / EOI deadline of that notice",
     "n_tender_notices": "Distinct tender notices linked before signing (more than 1 suggests re-advertisement)",
     "award_notification_date": "Award notification date from the linked award notice",
     "award_notice_date": "Publication date of the linked award notice",
     "n_named_firms_in_award_notice": "Firms named in the award notice (awarded + evaluated + rejected)",
     "wgi_gov_effectiveness": "WGI government effectiveness, borrower, year before signing",
     "wgi_control_corruption": "WGI control of corruption, year before signing",
     "wgi_rule_of_law": "WGI rule of law, year before signing",
     "wgi_regulatory_quality": "WGI regulatory quality, year before signing",
     "log_gdp_pc": "log GDP per capita (constant 2015 US$), year before signing",
     "region": "World Bank region", "major_sector": "Project major sector",
     "outcome_risk_band": "Outcome-model risk band of the project (active projects only)",
     "days_notice_to_deadline": "Advertising period: deadline minus notice date",
     "days_deadline_to_signing": "Evaluation to signature: signing minus deadline",
     "days_notice_to_signing": "Total: signing minus tender notice date",
     "days_award_notice_to_signing": "Signing minus award notification date",
     "timing_gap": "Why the contract is not timed (null when timed)",
     "is_timed": "True when a plausible tender-to-signing duration is available"},
    primary_key=["contract_id"])
add_foreign_key(f"{GOLD}.tender_timelines", ["contract_id"], f"{SILVER}.contracts", ["contract_id"])
print("tender_timelines:", n_timelines)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Coverage and durations
# MAGIC
# MAGIC **What:**
# MAGIC - coverage by competition level and by method: share of contracts with a measured duration, and why the rest are not timed;
# MAGIC - duration quantiles (days, notice -> signing) by category for openly competed, timed contracts;
# MAGIC - coverage by signing year.
# MAGIC
# MAGIC **Why:** the correct denominator matters: "40% of contracts are timed" means something different when 80% of contracts were never advertised.

# COMMAND ----------

tl = spark.table(f"{GOLD}.tender_timelines")
display(tl.groupBy("competition").agg(F.count("*").alias("contracts"), F.sum(F.col("is_timed").cast("int")).alias("timed"),
                                      F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy(F.desc("contracts")))
display(tl.groupBy("competition", "timing_gap").count().orderBy("competition", F.desc("count")))
display(tl.groupBy("procurement_method_name", "competition").agg(
            F.count("*").alias("contracts"), F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy(F.desc("contracts")).limit(15))
quantiles = F.expr("percentile_approx(days_notice_to_signing, array(0.1, 0.25, 0.5, 0.75, 0.9))")
display(tl.filter("is_timed AND competition = 'open'").groupBy("procurement_category_code").agg(
            F.count("*").alias("timed_contracts"), quantiles.alias("p10_p25_median_p75_p90_days"),
            F.round(F.avg("days_notice_to_deadline"), 1).alias("mean_advertising_days"),
            F.round(F.avg("n_tender_notices"), 2).alias("mean_tender_notices"))
        .orderBy("procurement_category_code"))
display(tl.filter("competition = 'open'").groupBy("signing_year").agg(
            F.count("*").alias("open_contracts"), F.round(F.avg(F.col("is_timed").cast("int")), 3).alias("share_timed"))
        .orderBy("signing_year"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Checks and summary
# MAGIC
# MAGIC **What:** keys, orphans, timeline consistency (no negative total durations among timed rows), and the headline numbers.
# MAGIC
# MAGIC **Why:** the gold table feeds a model; a negative duration or a duplicated contract would silently corrupt it.
# MAGIC
# MAGIC **How the counts fit together** (snapshot 2026-10-20):
# MAGIC
# MAGIC | Count | Value | Definition |
# MAGIC |---|---|---|
# MAGIC | contracts | 282,890 | rows of `tender_timelines` (one per contract) |
# MAGIC | tender notice before signing | 56,968 | contracts with a linked tender notice dated on or before signing (`days_notice_to_signing` not null; notices published after signing are never used) |
# MAGIC | timed, all methods | 56,156 | of those, `is_timed`: 812 dropped as implausible (notice > 3 years before signing 130, bid deadline after signing 378, bid deadline before notice 304); 19.9% of all contracts |
# MAGIC | timed, openly competed | **28,235** | `is_timed AND competition = 'open'`: 44.9% of the 62,828 openly competed contracts; the headline coverage and the phase-2 modelling population |
# MAGIC | median notice -> signing | 158 days (open) / 123 days (all timed) | the summary below prints the all-methods median; the per-category medians in section 7 (works 134, goods 129, consulting 314, non-consulting 120) are for openly competed contracts |

# COMMAND ----------

C = spark.table(f"{SILVER}.contracts")
timed = tl.filter("is_timed")
checks = [
    ("notice_contract_links", "duplicate PK", duplicate_keys(L, ["notice_id", "contract_id"]), "== 0"),
    ("notice_contract_links", "orphan notice_id", orphan_count(L, "notice_id", notices, "notice_id"), "== 0"),
    ("notice_contract_links", "orphan contract_id", orphan_count(L, "contract_id", C, "contract_id"), "== 0"),
    ("tender_timelines", "rows vs contracts", tl.count() - C.count(), "== 0"),
    ("tender_timelines", "duplicate contract_id", duplicate_keys(tl, ["contract_id"]), "== 0"),
    # can only fail if the "notice before signing" filter above is broken
    ("tender_timelines", "timed rows with negative notice->signing", timed.filter("days_notice_to_signing < 0").count(), "== 0"),
    ("tender_timelines", "contracts with a tender link", tl.filter("tender_notice_id IS NOT NULL").count(), "info"),
    ("tender_timelines", "contracts timed", timed.count(), "info"),
    ("tender_timelines", "share of all contracts timed", round(timed.count() / tl.count(), 3), "info"),
    ("tender_timelines", "share of open-competition contracts timed",
     round(timed.filter("competition = 'open'").count() / tl.filter("competition = 'open'").count(), 3), "info"),
    ("tender_timelines", "contracts with an award link", tl.filter("award_notice_date IS NOT NULL").count(), "info"),
    ("tender_timelines", "timed contracts without WGI (regional or missing year)", timed.filter("wgi_gov_effectiveness IS NULL").count(), "info"),
]
display(dq_report(checks))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run summary
# MAGIC
# MAGIC **What:** the headline numbers as the notebook's exit value.
# MAGIC
# MAGIC **Why:** a job run shows them without opening the notebook. (In its own cell: output displayed in the same cell as `dbutils.notebook.exit` is dropped from the run record.)

# COMMAND ----------

summary = {"links": n_links, "timelines": n_timelines, "timed": timed.count(),
           "timed_open_share": round(timed.filter("competition = 'open'").count() / tl.filter("competition = 'open'").count(), 3),
           "median_days_notice_to_signing": timed.agg(F.expr("percentile_approx(days_notice_to_signing, 0.5)")).first()[0]}
print(summary)
dbutils.notebook.exit(json.dumps(summary))
