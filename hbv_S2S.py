# -*- coding: utf-8 -*-
"""
Created on Wed Sep 20 13:57:28 2023

@author: hkoivusa

Model by Harri Koivusalo

HBV model literature source
Seibert, J., Vis, M.J.P. 2012. Teaching hydrological modeling with a user-friendly catchment-runoff-
model software package. Hydrol. Earth Syst. Sci., 16, 3315–3325. http://www.hydrol-earth-syst-
sci.net/16/3315/2012/hess-16-3315-2012.pdf  

Snow degree-day model literature source
Koskela J.J., Croke B.W.F., Koivusalo H., Jakeman A.J., Kokkonen T. 2012. Bayesian inference of uncertainties in 
precipitation-streamflow modeling in a snow affected catchment. Water Resources Research, 48, W11513, 19 
pp. https://doi.org/10.1029/2011WR011773

The model uses two impuit csv-files:
    met_input.csv, meteorological input data
    hbv_para.csv, mode parameter values
"""


import os
import numpy as np
import pandas as pd
from pandas import DataFrame

def run_hbv_model(met_input_csv):
    """
    Run HBV model using a given meteorological input CSV file.
    Returns a dictionary of output file paths.
    """

    print(f"[HBV Model] Using meteorological input file: {met_input_csv}")

    def get_data(f):
        df = pd.read_csv(f, skiprows=0)
        return df

    # --- HBV class ---
    class hbv:
        def __init__(self, para, j):
            self.swei = para[18]/1000.0
            self.swel = 0
            self.soilbox = para[19]/1000.0
            self.supperzone = para[20]/1000.0
            self.slowerzone = para[21]/1000.0

            maxbas = 1000
            if maxbas > 999:
                maxbas = 999

            c = np.zeros(int(maxbas)+1)
            qdel = np.zeros(int(maxbas)+1)

            maxbas = int(para[16])+1
            csum = 0
            for i in range(maxbas):
                c[i] = 2/(maxbas) - (((i+1)-(maxbas)/2)**2)**0.5 * 4/(maxbas)**2
                if c[i] < 0:
                    c[i] = 0
                csum += c[i]
                qdel[i] = 0
            for i in range(maxbas):
                c[i] = c[i]/csum

            self.cordinate = c
            self.runoff = qdel
            self.delayedrunoff = 0
            self.totalprecip = 0
            self.runoffinput = 0
            self.index = j

        def updateswe(self, minput, para, dt):
            swei = self.swei
            swel = self.swel
            airt = minput[4]
            pr = minput[3]/1000.0
            sweice = swei
            sweliq = swel

            if airt < para[0]:
                prs = pr * para[3]
                prr = 0.0
            elif airt > para[1]:
                prs = 0.0
                prr = pr * para[2]
            else:
                fraction_rain = (airt - para[0]) / (para[1] - para[0])
                prr = fraction_rain * pr * para[2]
                prs = pr - fraction_rain * pr
                prs = prs * para[3]

            tp = prs + prr

            if airt > para[0]:
                melt = para[5]/1000 * (airt - para[0])
                freez = 0.0
            else:
                melt = 0.0
                freez = para[6]/1000 * (para[0] - airt)

            if melt * dt > sweice + (1-para[4]) * prs * dt:
                melt = sweice/dt + sweliq/dt + (1-para[4])*(prr+prs)
                outflow = melt
                sweice = 0.0
                sweliq = 0.0
            else:
                if freez * dt > sweliq:
                    freez = sweliq/dt
                sweliq += ((1-para[4])*prr + melt - freez) * dt
                sweice += ((1-para[4])*prs + freez - melt) * dt
                outflow = 0.0
                if sweliq > para[7]*sweice:
                    outflow = sweliq/dt - para[7]*sweice/dt
                    sweliq = para[7]*sweice

            quickR = para[23] * outflow
            self.quickr = quickR
            self.rainmelt = outflow - quickR
            self.swei = sweice
            self.swel = sweliq
            self.interception = para[4]*(prr+prs)
            self.totalprecip = tp

        def updatehbvz(self, minput, para, dt):
            sbox = self.soilbox
            suz = self.supperzone
            slz = self.slowerzone
            swe = self.swei
            c = self.cordinate
            rainmelt = self.rainmelt
            quickr = self.quickr
            qdel = self.runoff

            potetr = para[17]*minput[5]/1000

            if sbox / para[8] > para[9]:
                eact = potetr
            else:
                eact = potetr * sbox / para[8] / para[9]
            if swe > 0:
                eact = 0

            recharge = rainmelt * (sbox / para[8])**para[10]
            inf = rainmelt - recharge
            sbox += dt * (inf - eact)

            if suz > para[11]:
                q0 = para[13] * (suz - para[11])
            else:
                q0 = 0.0

            q1 = para[14] * suz

            if para[12] > suz/dt + recharge - q0 - q1:
                perc = suz/dt + recharge - q0 - q1
                suz = 0.0
            else:
                perc = para[12]
                suz += dt * (recharge - perc - q0 - q1)

            q2 = para[15] * slz
            slz += dt * (perc - q2)

            q = q0 + q1 + q2 + quickr

            maxbas = int(para[16]) + 1
            for j in range(maxbas):
                qdel[j] = qdel[j] + c[j] * q

            self.delayedrunoff = qdel[0]

            for j in range(maxbas-1):
                qdel[j] = qdel[j+1]

            self.soilbox = sbox
            self.supperzone = suz
            self.slowerzone = slz
            self.runoff = qdel
            self.eactual = eact
            self.runoffinput = q

    # ---------------- Main computation ----------------
    globaldeltat = 1
    subdtnhbv = 24
    deltat = globaldeltat / subdtnhbv

    hydroinput = np.array(get_data(met_input_csv))
    nhydroinput = len(hydroinput)
    hydropara = np.array(get_data('hbv_para.csv').iloc[:,0:3])

    maxbas = 100
    numberofhbvs = 3
    delayedrunoff = np.zeros((numberofhbvs, nhydroinput))
    hbvsub = []

    output_files = {}

    for j in range(numberofhbvs):
        hbvsub.append(hbv(hydropara[:, j], j))

        totpr = np.zeros(nhydroinput)
        einterc = np.zeros(nhydroinput)
        eactual = np.zeros(nhydroinput)
        runoffinp = np.zeros(nhydroinput)
        modelswe = np.zeros(nhydroinput)
        modelsoilw = np.zeros(nhydroinput)
        soilbox = np.zeros(nhydroinput)
        supperzone = np.zeros(nhydroinput)
        slowerzone = np.zeros(nhydroinput)
        sdepth = np.zeros(nhydroinput)

        for i in range(nhydroinput):
            for ii in range(subdtnhbv):
                hbvsub[j].updateswe(hydroinput[i, :], hydropara[:, j], deltat)
                hbvsub[j].updatehbvz(hydroinput[i, :], hydropara[:, j], deltat)
                totpr[i] += deltat*hbvsub[j].totalprecip
                einterc[i] += deltat*hbvsub[j].interception
                eactual[i] += deltat*hbvsub[j].eactual
                delayedrunoff[j, i] += deltat*hbvsub[j].delayedrunoff
                runoffinp[i] += deltat*hbvsub[j].runoffinput

            modelswe[i] = hbvsub[j].swei + hbvsub[j].swel
            modelsoilw[i] = hbvsub[j].soilbox + hbvsub[j].supperzone + hbvsub[j].slowerzone
            soilbox[i] = hbvsub[j].soilbox
            supperzone[i] = hbvsub[j].supperzone
            slowerzone[i] = hbvsub[j].slowerzone
            sdepth[i] = (hbvsub[j].swei + hbvsub[j].swel)/hydropara[22, j]

        if j == 0:
            fout = 'hbv_output_agric.csv'
        elif j == 1:
            fout = 'hbv_output_forest.csv'
        else:
            fout = 'hbv_output_urban.csv'

        hbvout = DataFrame({
            'Year': hydroinput[:, 0],
            'Month': hydroinput[:, 1],
            'Day': hydroinput[:, 2],
            'total_precipitation mm': 1000*totpr,
            'interception mm': 1000*einterc,
            'actual_evapotranspiration mm': 1000*eactual,
            'delayedrunoff mm': 1000*delayedrunoff[j, :],
            'runoffinput mm': 1000*runoffinp,
            'snow_water_equivalent mm': 1000*modelswe,
            'soil_water_storage mm': 1000*modelsoilw,
            'soilbox mm': 1000*soilbox,
            'supperzone mm': 1000*supperzone,
            'slowerzone mm': 1000*slowerzone,
            'snow depth cm': 100*sdepth
        })

        hbvout.to_csv(fout)
        output_files[f"landuse_{j}"] = os.path.abspath(fout)
        print(f"HBV output saved: {output_files[f'landuse_{j}']}")

    # Total runoff
    total_outfile = 'hbv_output_totalrunoff.csv'
    hbvtotalout = DataFrame({
        'Year': hydroinput[:, 0],
        'Month': hydroinput[:, 1],
        'Day': hydroinput[:, 2],
        'totalrunoff mm': 1000*(delayedrunoff[0,:]*hydropara[24,0] + delayedrunoff[1,:]*hydropara[24,1] + delayedrunoff[2,:]*hydropara[24,2]),
        'agricrunoff mm': 1000*(delayedrunoff[0,:]*hydropara[24,0]),
        'forestrunoff mm': 1000*(delayedrunoff[1,:]*hydropara[24,1]),
        'urbanrunoff mm': 1000*(delayedrunoff[2,:]*hydropara[24,2])
    })
    hbvtotalout.to_csv(total_outfile)
    output_files["total_runoff"] = os.path.abspath(total_outfile)
    print(f"Total runoff saved: {output_files['total_runoff']}")

    return output_files
