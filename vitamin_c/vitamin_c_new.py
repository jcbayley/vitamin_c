import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
import tensorflow_probability as tfp
tfd = tfp.distributions
import time
from lal import GreenwichMeanSiderealTime
from astropy.time import Time
from astropy import coordinates as coord
import corner
import os
import shutil
import h5py
import json
import sys
from sys import exit
from universal_divergence import estimate
import natsort
import plotting
from tensorflow.keras import regularizers

from vitamin_c_model import CVAE
from load_data import load_data, load_samples, convert_ra_to_hour_angle, convert_hour_angle_to_ra, DataLoader

def get_param_index(all_pars,pars,sky_extra=None):
    """ 
    Get the list index of requested source parameter types
    """
    # identify the indices of wrapped and non-wrapped parameters - clunky code
    mask = []
    idx = []

    # loop over inference params
    for i,p in enumerate(all_pars):

        # loop over wrapped params
        flag = False
        for q in pars:
            if p==q:
                flag = True    # if inf params is a wrapped param set flag

        # record the true/false value for this inference param
        if flag==True:
            mask.append(True)
            idx.append(i)
        elif flag==False:
            mask.append(False)

    if sky_extra is not None:
        if sky_extra:
            mask.append(True)
            idx.append(len(all_pars))
        else:
            mask.append(False)

    return mask, idx, np.sum(mask)



def plot_losses(train_loss, val_loss, epoch, run='testing'):
    """
    plots the losses
    """
    plt.figure()
    plt.semilogx(np.arange(1,epoch+1),train_loss[:epoch,0],'b',label='RECON')
    plt.semilogx(np.arange(1,epoch+1),train_loss[:epoch,1],'r',label='KL')
    plt.semilogx(np.arange(1,epoch+1),train_loss[:epoch,2],'g',label='TOTAL')
    plt.semilogx(np.arange(1,epoch+1),val_loss[:epoch,0],'--b',alpha=0.5)
    plt.semilogx(np.arange(1,epoch+1),val_loss[:epoch,1],'--r',alpha=0.5)
    plt.semilogx(np.arange(1,epoch+1),val_loss[:epoch,2],'--g',alpha=0.5)
    plt.xlabel('epoch')
    plt.ylabel('loss')
    plt.legend()
    plt.grid()
    plt.ylim([np.min(1.1*train_loss[int(0.1*epoch):epoch,:]),np.max(1.1*train_loss[int(0.1*epoch):epoch,:])])
    plt.savefig('%s/loss.png' % (run))
    plt.close()

    # save loss data to text file
    loss_file = '%s/loss.txt' % (run)
    data = np.concatenate([train_loss[:epoch,:],val_loss[:epoch,:]],axis=1)
    np.savetxt(loss_file,data)

def plot_losses_zoom(train_loss, val_loss, epoch, ind_start, run='testing'):
    """
    plots the losses
    """
    plt.figure()
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],train_loss[ind_start:epoch,0],'b',label='RECON')
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],train_loss[ind_start:epoch,1],'r',label='KL')
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],train_loss[ind_start:epoch,2],'g',label='TOTAL')
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],val_loss[ind_start:epoch,0],'--b',alpha=0.5)
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],val_loss[ind_start:epoch,1],'--r',alpha=0.5)
    plt.semilogx(np.arange(1,epoch+1)[ind_start:],val_loss[ind_start:epoch,2],'--g',alpha=0.5)
    plt.xlabel('epoch')
    plt.ylabel('loss')
    plt.legend()
    plt.grid()
    #plt.ylim([np.min(1.1*train_loss[int(0.1*epoch):epoch,:]),np.max(1.1*train_loss[int(0.1*epoch):epoch,:])])
    plt.savefig('%s/loss_zoom.png' % (run))
    plt.close()


 
def plot_KL(KL_samples, step, run='testing'):
    """
    plots the KL evolution
    """
    # arrives in shape n_kl,n_test,3
    N = KL_samples.shape[0]
#    KL_samples = np.transpose(KL_samples,[2,1,0])   # re-order axes
#    print(list(np.linspace(0,len(params['samplers'][1:])-1,num=len(params['samplers'][1:]), dtype=int))[::-1])
#    print(KL_samples.shape)
#    exit()
#    KL_samples = np.transpose(KL_samples, list(np.linspace(0,len(params['samplers'][1:])-1,num=len(params['samplers'][1:]), dtype=int))[::-1])    
    ls = ['-','--',':']
    c = ['C0','C1','C2','C3']
    fig, axs = plt.subplots(3, sharex=True, sharey=True, figsize=(6.4,14.4))
    for i,kl_s in enumerate(KL_samples):   # loop over samplers
        for j,kl in enumerate(kl_s):     # loop over test cases
            axs[i].semilogx(np.arange(1,N+1)*step,kl,ls[i],color=c[j])
            axs[i].plot(N*step,kl[-1],'.',color=c[j])
            axs[i].grid()
    plt.xlabel('epoch')
    plt.ylabel('KL')
    plt.ylim([-0.2,1.0])
    plt.savefig('%s/kl.png' % (run))
    plt.close()


def plot_posterior(samples,x_truth,epoch,idx,run='testing',all_other_samples=None):
    """
    plots the posteriors
    """

    # trim samples from outside the cube
    mask = []
    for s in samples:
        if (np.all(s>=0.0) and np.all(s<=1.0)):
            mask.append(True)
        else:
            mask.append(False)
    samples = tf.boolean_mask(samples,mask,axis=0)
    print('identified {} good samples'.format(samples.shape[0]))
    print(np.array(all_other_samples).shape)
    if samples.shape[0]<100:
        print('... Bad run, not doing posterior plotting.')
        return [-1.0] * len(params['samplers'][1:])

    # define general plotting arguments
    defaults_kwargs = dict(
                    bins=50, smooth=0.9, label_kwargs=dict(fontsize=16),
                    title_kwargs=dict(fontsize=16),
                    truth_color='tab:orange', quantiles=[0.16, 0.84],
                    levels=(0.68,0.90,0.95), density=True,
                    plot_density=False, plot_datapoints=True,
                    max_n_ticks=3)

    # 1-d hist kwargs for normalisation
    hist_kwargs = dict(density=True,color='tab:red')
    hist_kwargs_other = dict(density=True,color='tab:blue')
    hist_kwargs_other2 = dict(density=True,color='tab:green')

    if all_other_samples is not None:
        KL_est = []
        for i, other_samples in enumerate(all_other_samples):
            true_post = np.zeros([other_samples.shape[0],masks["bilby_ol_len"]])
            true_x = np.zeros(masks["inf_ol_len"])
            true_XS = np.zeros([samples.shape[0],masks["inf_ol_len"]])
            ol_pars = []
            cnt = 0
            for inf_idx,bilby_idx in zip(masks["inf_ol_idx"],masks["bilby_ol_idx"]):
                inf_par = params['inf_pars'][inf_idx]
                bilby_par = params['bilby_pars'][bilby_idx]
                true_XS[:,cnt] = (samples[:,inf_idx] * (bounds[inf_par+'_max'] - bounds[inf_par+'_min'])) + bounds[inf_par+'_min']
                true_post[:,cnt] = (other_samples[:,bilby_idx] * (bounds[bilby_par+'_max'] - bounds[bilby_par+'_min'])) + bounds[bilby_par + '_min']
                true_x[cnt] = (x_truth[inf_idx] * (bounds[inf_par+'_max'] - bounds[inf_par+'_min'])) + bounds[inf_par + '_min']
                ol_pars.append(inf_par)
                cnt += 1
            parnames = []
            for k_idx,k in enumerate(params['rand_pars']):
                if np.isin(k, ol_pars):
                    parnames.append(params['corner_labels'][k])

            # convert to RA
            true_XS = convert_hour_angle_to_ra(true_XS,params,ol_pars)
            #true_x = convert_hour_angle_to_ra(np.reshape(true_x,[1,true_XS.shape[1]]),params,ol_pars).flatten()
            old_true_post = true_post                 

            samples_file = '{}/posterior_samples_epoch_{}_event_{}_vit.txt'.format(run,epoch,idx)
            np.savetxt(samples_file,true_XS)

            # compute KL estimate
            idx1 = np.random.randint(0,true_XS.shape[0],2000)
            idx2 = np.random.randint(0,true_post.shape[0],2000)
            """
            try:
                current_KL = 0.5*(estimate(true_XS[idx1,:],true_post[idx2,:],n_jobs=4) + estimate(true_post[idx2,:],true_XS[idx1,:],n_jobs=4))
            except:
                current_KL = -1.0
                pass
            """
            current_KL = -1
            KL_est.append(current_KL)

            other_samples_file = '{}/posterior_samples_epoch_{}_event_{}_{}.txt'.format(run,epoch,idx,i)
            np.savetxt(other_samples_file,true_post)

            if i==0:
                figure = corner.corner(true_post, **defaults_kwargs,labels=parnames,
                           color='tab:blue',
                           show_titles=True, hist_kwargs=hist_kwargs_other)
            else:

                # compute KL estimate
                idx1 = np.random.randint(0,old_true_post.shape[0],2000)
                idx2 = np.random.randint(0,true_post.shape[0],2000)
                """
                try:
                    current_KL = 0.5*(estimate(old_true_post[idx1,:],true_post[idx2,:],n_jobs=4) + estimate(true_post[idx2,:],old_true_post[idx1,:],n_jobs=4))
                except:
                    current_KL = -1.0
                    pass
                """
                current_KL=-1
                KL_est.append(current_KL)

                corner.corner(true_post,**defaults_kwargs,
                           color='tab:green',
                           show_titles=True, fig=figure, hist_kwargs=hist_kwargs_other2)
        
        for j,KL in enumerate(KL_est):    
            plt.annotate('KL = {:.3f}'.format(KL),(0.2,0.95-j*0.02),xycoords='figure fraction',fontsize=18)

        corner.corner(true_XS,**defaults_kwargs,
                           color='tab:red',
                           fill_contours=True, truths=true_x,
                           show_titles=True, fig=figure, hist_kwargs=hist_kwargs)
        if epoch == 'pub_plot':
            print('Saved output to %s/comp_posterior_%s_event_%d.png' % (run,epoch,idx))
            plt.savefig('%s/comp_posterior_%s_event_%d.png' % (run,epoch,idx))
        else:
            print('Saved output to %s/comp_posterior_epoch_%d_event_%d.png' % (run,epoch,idx))
            plt.savefig('%s/comp_posterior_epoch_%d_event_%d.png' % (run,epoch,idx))
        plt.close()
        return KL_est

    else:
        # Get corner parnames to use in plotting labels
        parnames = []
        for k_idx,k in enumerate(params['rand_pars']):
            if np.isin(k, params['inf_pars']):
                parnames.append(params['corner_labels'][k])
        # un-normalise full inference parameters
        full_true_x = np.zeros(len(params['inf_pars']))
        new_samples = np.zeros([samples.shape[0],len(params['inf_pars'])])
        for inf_par_idx,inf_par in enumerate(params['inf_pars']):
            new_samples[:,inf_par_idx] = (samples[:,inf_par_idx] * (bounds[inf_par+'_max'] - bounds[inf_par+'_min'])) + bounds[inf_par+'_min']
            full_true_x[inf_par_idx] = (x_truth[inf_par_idx] * (bounds[inf_par+'_max'] - bounds[inf_par+'_min'])) + bounds[inf_par + '_min']
        new_samples = convert_hour_angle_to_ra(new_samples,params,params['inf_pars'])
        full_true_x = convert_hour_angle_to_ra(np.reshape(full_true_x,[1,samples.shape[1]]),params,params['inf_pars']).flatten()       

        figure = corner.corner(new_samples,**defaults_kwargs,labels=parnames,
                           color='tab:red',
                           fill_contours=True, truths=full_true_x,
                           show_titles=True, hist_kwargs=hist_kwargs)
        if epoch == 'pub_plot':
            plt.savefig('%s/full_posterior_%s_event_%d.png' % (run,epoch,idx))
        else:
            plt.savefig('%s/full_posterior_epoch_%d_event_%d.png' % (run,epoch,idx))
        plt.close()
    return -1.0

def plot_latent(mu_r1, z_r1, mu_q, z_q, epoch, idx, run='testing'):

    # define general plotting arguments
    defaults_kwargs = dict(
                    bins=50, smooth=0.9, label_kwargs=dict(fontsize=16),
                    title_kwargs=dict(fontsize=16),
                    truth_color='tab:orange', quantiles=[0.16, 0.84],
                    levels=(0.68,0.90,0.95), density=True,
                    plot_density=False, plot_datapoints=True,
                    max_n_ticks=3)

    # 1-d hist kwargs for normalisation
    hist_kwargs = dict(density=True,color='tab:red')
    hist_kwargs_other = dict(density=True,color='tab:blue')

    
    figure = corner.corner(np.array(z_q), **defaults_kwargs,
                           color='tab:blue',
                           show_titles=True, hist_kwargs=hist_kwargs_other)
    corner.corner(np.array(z_r1),**defaults_kwargs,
                           color='tab:red',
                           fill_contours=True,
                           show_titles=True, fig=figure, hist_kwargs=hist_kwargs)
    # Extract the axes
    z_dim = z_r1.shape[1]
    axes = np.array(figure.axes).reshape((z_dim, z_dim))

    # Loop over the histograms
    for yi in range(z_dim):
        for xi in range(yi):
            ax = axes[yi, xi]
            ax.plot(mu_r1[0,:,xi], mu_r1[0,:,yi], "sr")
            ax.plot(mu_q[0,xi], mu_q[0,yi], "sb")
    if epoch == 'pub_plot':
        plt.savefig('%s/latent_%s_event_%d.png' % (run,epoch,idx))
    else:
        plt.savefig('%s/latent_epoch_%d_event_%d.png' % (run,epoch,idx))
    plt.close()

params = './params_files/params.json'
bounds = './params_files/bounds.json'
fixed_vals = './params_files/fixed_vals.json'
run = time.strftime('%y-%m-%d-%X-%Z')
EPS = 1e-3

# Load parameters files
with open(params, 'r') as fp:
    params = json.load(fp)
with open(bounds, 'r') as fp:
    bounds = json.load(fp)
with open(fixed_vals, 'r') as fp:
    fixed_vals = json.load(fp)

# if doing hour angle, use hour angle bounds on RA                                                                                                                       
bounds['ra_min'] = convert_ra_to_hour_angle(bounds['ra_min'],params,None,single=True)
bounds['ra_max'] = convert_ra_to_hour_angle(bounds['ra_max'],params,None,single=True)
print('... converted RA bounds to hour angle')
masks = {}
masks["inf_ol_mask"], masks["inf_ol_idx"], masks["inf_ol_len"] = get_param_index(params['inf_pars'],params['bilby_pars'])
masks["bilby_ol_mask"], masks["bilby_ol_idx"], masks["bilby_ol_len"] = get_param_index(params['bilby_pars'],params['inf_pars'])


# identify the indices of different sets of physical parameters                                                                                                          
masks["vonmise_mask"], masks["vonmise_idx_mask"], masks["vonmise_len"] = get_param_index(params['inf_pars'],params['vonmise_pars'])
masks["gauss_mask"], masks["gauss_idx_mask"], masks["gauss_len"] = get_param_index(params['inf_pars'],params['gauss_pars'])
masks["sky_mask"], masks["sky_idx_mask"], masks["sky_len"] = get_param_index(params['inf_pars'],params['sky_pars'])
masks["ra_mask"], masks["ra_idx_mask"], masks["ra_len"] = get_param_index(params['inf_pars'],['ra'])
masks["dec_mask"], masks["dec_idx_mask"], masks["dec_len"] = get_param_index(params['inf_pars'],['dec'])
masks["m1_mask"], masks["m1_idx_mask"], masks["m1_len"] = get_param_index(params['inf_pars'],['mass_1'])
masks["m2_mask"], masks["m2_idx_mask"], masks["m2_len"] = get_param_index(params['inf_pars'],['mass_2'])
#idx_mask = np.argsort(gauss_idx_mask + vonmise_idx_mask + m1_idx_mask + m2_idx_mask + sky_idx_mask) # + dist_idx_mask)                                                  
masks["idx_mask"] = np.argsort(masks["m1_idx_mask"] + masks["m2_idx_mask"] + masks["gauss_idx_mask"] + masks["vonmise_idx_mask"]) # + sky_idx_mask)                      
masks["dist_mask"], masks["dist_idx_mask"], masks["dis_len"] = get_param_index(params['inf_pars'],['luminosity_distance'])
masks["not_dist_mask"], masks["not_dist_idx_mask"], masks["not_dist_len"] = get_param_index(params['inf_pars'],['mass_1','mass_2','psi','phase','geocent_time','theta_jn','ra','dec','a_1','a_2','tilt_1','tilt_2','phi_12','phi_jl'])
masks["phase_mask"], masks["phase_idx_mask"], masks["phase_len"] = get_param_index(params['inf_pars'],['phase'])
masks["not_phase_mask"], masks["not_phase_idx_mask"], masks["not_phase_len"] = get_param_index(params['inf_pars'],['mass_1','mass_2','luminosity_distance','psi','geocent_time','theta_jn','ra','dec','a_1','a_2','tilt_1','tilt_2','phi_12','phi_jl'])
masks["geocent_mask"], masks["geocent_idx_mask"], masks["geocent_len"] = get_param_index(params['inf_pars'],['geocent_time'])
masks["not_geocent_mask"], masks["not_geocent_idx_mask"], masks["not_geocent_len"] = get_param_index(params['inf_pars'],['mass_1','mass_2','luminosity_distance','psi','phase','theta_jn','ra','dec','a_1','a_2','tilt_1','tilt_2','phi_12','phi_jl'])
masks["xyz_mask"], masks["xyz_idx_mask"], masks["xyz_len"] = get_param_index(params['inf_pars'],['luminosity_distance','ra','dec'])
masks["not_xyz_mask"], masks["not_xyz_idx_mask"], masks["not_xyz_len"] = get_param_index(params['inf_pars'],['mass_1','mass_2','psi','phase','geocent_time','theta_jn','a_1','a_2','tilt_1','tilt_2','phi_12','phi_jl'])
masks["periodic_mask"], masks["periodic_idx_mask"], masks["periodic_len"] = get_param_index(params['inf_pars'],['ra','phase','psi','phi_12','phi_jl'])
masks["nonperiodic_mask"], masks["nonperiodic_idx_mask"], masks["nonperiodic_len"] = get_param_index(params['inf_pars'],['mass_1','mass_2','luminosity_distance','geocent_time','theta_jn','dec','a_1','a_2','tilt_1','tilt_2'])
masks["idx_xyz_mask"] = np.argsort(masks["xyz_idx_mask"] + masks["not_xyz_idx_mask"])
masks["idx_dist_mask"] = np.argsort(masks["not_dist_idx_mask"] + masks["dist_idx_mask"])
masks["idx_phase_mask"] = np.argsort(masks["not_phase_idx_mask"] + masks["phase_idx_mask"])
masks["idx_geocent_mask"] = np.argsort(masks["not_geocent_idx_mask"] + masks["geocent_idx_mask"])
masks["idx_periodic_mask"] = np.argsort(masks["nonperiodic_idx_mask"] + masks["periodic_idx_mask"])
print(masks["xyz_mask"])
print(masks["not_xyz_mask"])
print(masks["idx_xyz_mask"])
#masses_len = m1_len + m2_len                                                                                                                                            
print(params['inf_pars'])
print(masks["vonmise_mask"],masks["vonmise_idx_mask"])
print(masks["gauss_mask"],masks["gauss_idx_mask"])
print(masks["m1_mask"],masks["m1_idx_mask"])
print(masks["m2_mask"],masks["m2_idx_mask"])
print(masks["sky_mask"],masks["sky_idx_mask"])
print(masks["idx_mask"])

# define which gpu to use during training
gpu_num = str(params['gpu_num'])   
os.environ["CUDA_VISIBLE_DEVICES"]=gpu_num
print('... running on GPU {}'.format(gpu_num))

# Let GPU consumption grow as needed
config = tf.compat.v1.ConfigProto()
config.gpu_options.allow_growth = True
session = tf.compat.v1.Session(config=config)
print('... letting GPU consumption grow as needed')

train_loss_metric = tf.keras.metrics.Mean('train_loss', dtype=tf.float32)
train_log_dir = params['plot_dir'] + '/logs'




def ramp_func(epoch,start,ramp_length, n_cycles):
    i = (epoch-start)/(2.0*ramp_length)
    print(epoch,i)
    if i<0:
        return 0.0
    if i>=n_cycles:
        return 1.0
    return min(1.0,2.0*np.remainder(i,1.0))


#@tf.function

def paper_plots(test_dataset, y_data_test, x_data_test, model, params, plot_dir, run, bilby_samples):
    """ Make publication plots
    """
    epoch = 'pub_plot'; ramp = 1
    plotter = plotting.make_plots(params, None, None, x_data_test) 

    for step, (x_batch_test, y_batch_test) in test_dataset.enumerate():
        mu_r1, z_r1, mu_q, z_q = gen_z_samples(model, x_batch_test, y_batch_test, nsamples=1000)
        plot_latent(mu_r1,z_r1,mu_q,z_q,epoch,step,run=plot_dir)
        start_time_test = time.time()
        samples = gen_samples(model, y_batch_test, ramp=ramp, nsamples=params['n_samples'])
        end_time_test = time.time()
        if np.any(np.isnan(samples)):
            print('Found nans in samples. Not making plots')
            for k,s in enumerate(samples):
                if np.any(np.isnan(s)):
                    print(k,s)
            KL_est = [-1,-1,-1]
        else:
            print('Run {} Testing time elapsed for {} samples: {}'.format(run,params['n_samples'],end_time_test - start_time_test))
            KL_est = plot_posterior(samples,x_batch_test[0,:],epoch,step,all_other_samples=bilby_samples[:,step,:],run=plot_dir)
            _ = plot_posterior(samples,x_batch_test[0,:],epoch,step,run=plot_dir)
    print('... Finished making publication plots! Congrats fam.')

    # Make p-p plots
    plotter.plot_pp(model, y_data_test, x_data_test, params, bounds, inf_ol_idx, bilby_ol_idx)
    print('... Finished making p-p plots!')

    # Make KL plots
    plotter.gen_kl_plots(model,y_data_test, x_data_test, params, bounds, inf_ol_idx, bilby_ol_idx)
    print('... Finished making KL plots!')    

    return

def run_vitc_old(params, x_data_train, y_data_train, x_data_val, y_data_val, x_data_test, y_data_test, y_data_test_noisefree, save_dir, truth_test, bounds, fixed_vals, bilby_samples, snrs_test=None):

    epochs = params['num_iterations']
    train_size = params['load_chunk_size']
    batch_size = params['batch_size']
    val_size = params['val_dataset_size']
    test_size = params['r']
    plot_dir = params['plot_dir']
    plot_cadence = int(0.5*params['plot_interval'])
    # Include the epoch in the file name (uses `str.format`)
    checkpoint_path = "inverse_model_%s/model.ckpt" % params['run_label']
    checkpoint_dir = os.path.dirname(checkpoint_path)
    make_paper_plots = params['make_paper_plots']
    hyper_par_tune = False

    # if doing hour angle, use hour angle bounds on RA
    bounds['ra_min'] = convert_ra_to_hour_angle(bounds['ra_min'],params,None,single=True)
    bounds['ra_max'] = convert_ra_to_hour_angle(bounds['ra_max'],params,None,single=True)
    print('... converted RA bounds to hour angle')

    # load the training data
    if not make_paper_plots:
        x_data_train, y_data_train, _, snrs_train = load_data(params,bounds,fixed_vals,params['train_set_dir'],params['inf_pars'])
        x_data_val, y_data_val, _, snrs_val = load_data(params,bounds,fixed_vals,params['val_set_dir'],params['inf_pars'])

        # randomise distance    
        old_d = bounds['luminosity_distance_min'] + tf.boolean_mask(x_data_train,masks["dist_mask"],axis=1)*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
        new_x = tf.random.uniform(shape=tf.shape(old_d), minval=0.0, maxval=1.0, dtype=tf.dtypes.float32)
        new_d = bounds['luminosity_distance_min'] + new_x*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
        x_data_train = tf.gather(tf.concat([tf.reshape(tf.boolean_mask(x_data_train,masks["not_dist_mask"],axis=1),[-1,tf.shape(x_data_train)[1]-1]), tf.reshape(new_x,[-1,1])],axis=1),tf.constant(masks["idx_dist_mask"]),axis=1)
        dist_scale = tf.tile(tf.expand_dims(old_d/new_d,axis=1),(1,tf.shape(y_data_train)[1],1))

        y_normscale = tf.cast(params['y_normscale'], dtype=tf.float32)
        noiseamp = 1
        y_data_train = (y_data_train*dist_scale + noiseamp*tf.random.normal(shape=tf.shape(y_data_train), mean=0.0, stddev=1.0, dtype=tf.float32))/y_normscale

        # randomise distance    
        old_d = bounds['luminosity_distance_min'] + tf.boolean_mask(x_data_val,masks["dist_mask"],axis=1)*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
        new_x = tf.random.uniform(shape=tf.shape(old_d), minval=0.0, maxval=1.0, dtype=tf.dtypes.float32)
        new_d = bounds['luminosity_distance_min'] + new_x*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
        x_data_val = tf.gather(tf.concat([tf.reshape(tf.boolean_mask(x_data_val,masks["not_dist_mask"],axis=1),[-1,tf.shape(x_data_val)[1]-1]), tf.reshape(new_x,[-1,1])],axis=1),tf.constant(masks["idx_dist_mask"]),axis=1)
        dist_scale_val = tf.tile(tf.expand_dims(old_d/new_d,axis=1),(1,tf.shape(y_data_val)[1],1))

        y_data_val = (y_data_val*dist_scale_val + noiseamp*tf.random.normal(shape=tf.shape(y_data_val), mean=0.0, stddev=1.0, dtype=tf.float32))/y_normscale


    x_data_test, y_data_test_noisefree, y_data_test, snrs_test = load_data(params,bounds,fixed_vals,params['test_set_dir'],params['inf_pars'],test_data=True)
    y_data_test = y_data_test[:params['r'],:,:]; x_data_test = x_data_test[:params['r'],:]

    # load precomputed samples
    bilby_samples = []
    for sampler in params['samplers'][1:]:
        bilby_samples.append(load_samples(params,sampler, bounds = bounds))
    bilby_samples = np.array(bilby_samples)
    #bilby_samples = np.array([load_samples(params,'dynesty'),load_samples(params,'ptemcee'),load_samples(params,'cpnest')])

    if not make_paper_plots:
        if not hyper_par_tune:
            train_dataset = (tf.data.Dataset.from_tensor_slices((x_data_train,y_data_train))
                             .shuffle(train_size).batch(batch_size))
        else:
            train_dataset = (tf.data.Dataset.from_tensor_slices(({'image': y_data_train},{'label': x_data_train}))
                             .shuffle(train_size))#.batch(batch_size))
        val_dataset = (tf.data.Dataset.from_tensor_slices((x_data_val,y_data_val))
                        .shuffle(val_size).batch(batch_size))
    test_dataset = (tf.data.Dataset.from_tensor_slices((x_data_test,y_data_test))
                    .batch(1))

    train_loss_metric = tf.keras.metrics.Mean('train_loss', dtype=tf.float32)
    train_summary_writer = tf.summary.create_file_writer(train_log_dir)

    if params['resume_training']:
        model = CVAE(x_data_train.shape[1], params['ndata'],
                     y_data_train.shape[2], params['z_dimension'], params['n_modes'], params, bounds = bounds, masks = masks)
        # Load the previously saved weights
        latest = tf.train.latest_checkpoint(checkpoint_dir)
        model.load_weights(latest)
        print('... loading in previous model %s' % checkpoint_path)
    else:
        model = CVAE(x_data_test.shape[1], params['ndata'],
                     y_data_test.shape[2], params['z_dimension'], params['n_modes'], params, bounds, masks)


    # Make publication plots
    if make_paper_plots:
        print('... Making plots for publication.')
        # Load the previously saved weights
        latest = tf.train.latest_checkpoint(checkpoint_dir)
        model.load_weights(latest)
        print('... loading in previous model %s' % checkpoint_path)
        paper_plots(test_dataset, y_data_test, x_data_test, model, params, plot_dir, run, bilby_samples)
        return

    # start the training loop
    train_loss = np.zeros((epochs,3))
    val_loss = np.zeros((epochs,3))
    ramp_start = params['ramp_start']
    ramp_length = params['ramp_end']
    ramp_cycles = 1
    KL_samples = []

    # Keras hyperparameter optimization
    if hyper_par_tune:
        import keras_hyper_optim
        del model
        keras_hyper_optim.main(train_dataset, val_dataset)
        exit()

    # log params used for this run
    path = params['plot_dir']
    shutil.copy('./vitamin_c_new.py',path)
    shutil.copy('./vitamin_c_model.py',path)
    shutil.copy('./load_data.py',path)
    shutil.copy('./params_files/params.json',path)

    optimizer = tf.keras.optimizers.Adam(1e-5)

    for epoch in range(1, epochs + 1):

        train_loss_kl_q = 0.0
        train_loss_kl_r1 = 0.0
        start_time_train = time.time()
        if params['resume_training']:
            ramp = ramp = tf.convert_to_tensor(1.0)
            print('... Not using ramp.')
        else:
            ramp = tf.convert_to_tensor(ramp_func(epoch,ramp_start,ramp_length,ramp_cycles), dtype=tf.float32)
        for step, (x_batch_train, y_batch_train) in train_dataset.enumerate():
            temp_train_r_loss, temp_train_kl_loss = model.train_step(x_batch_train, y_batch_train, optimizer, ramp=ramp)
            train_loss[epoch-1,0] += temp_train_r_loss
            train_loss[epoch-1,1] += temp_train_kl_loss
        train_loss[epoch-1,2] = train_loss[epoch-1,0] + ramp*train_loss[epoch-1,1]
        train_loss[epoch-1,:] /= float(step+1)
        end_time_train = time.time()
        with train_summary_writer.as_default():
            tf.summary.scalar('loss', train_loss_metric.result(), step=epoch)
        train_loss_metric.reset_states()

        start_time_val = time.time()
        for step, (x_batch_val, y_batch_val) in val_dataset.enumerate():
            temp_val_r_loss, temp_val_kl_loss = model.compute_loss(x_batch_val, y_batch_val)
            val_loss[epoch-1,0] += temp_val_r_loss
            val_loss[epoch-1,1] += temp_val_kl_loss
        val_loss[epoch-1,2] = val_loss[epoch-1,0] + ramp*val_loss[epoch-1,1]
        val_loss[epoch-1,:] /= float(step+1)
        end_time_val = time.time()

        print('Epoch: {}, Run {}, Training RECON: {}, KL: {}, TOTAL: {}, time elapsed: {}'
            .format(epoch, run, train_loss[epoch-1,0], train_loss[epoch-1,1], train_loss[epoch-1,2], end_time_train - start_time_train))
        print('Epoch: {}, Run {}, Validation RECON: {}, KL: {}, TOTAL: {}, time elapsed {}'
            .format(epoch, run, val_loss[epoch-1,0], val_loss[epoch-1,1], val_loss[epoch-1,2], end_time_val - start_time_val))

        if epoch % params['save_interval'] == 0:
            # Save the weights using the `checkpoint_path` format
            model.save_weights(checkpoint_path)
            print('... Saved model %s ' % checkpoint_path)

        # update loss plot
        plot_losses(train_loss, val_loss, epoch, run=plot_dir)
        if epoch > ramp_start + ramp_length + 2:
            plot_losses_zoom(train_loss, val_loss, epoch, run=plot_dir, ind_start = ramp_start + ramp_length)


        # generate and plot posterior samples for the latent space and the parameter space 
        if epoch % plot_cadence == 0:
            for step, (x_batch_test, y_batch_test) in test_dataset.enumerate():             
                mu_r1, z_r1, mu_q, z_q = model.gen_z_samples(x_batch_test, y_batch_test, nsamples=1000)
                plot_latent(mu_r1,z_r1,mu_q,z_q,epoch,step,run=plot_dir)
                start_time_test = time.time()
                samples = model.gen_samples(y_batch_test, ramp=ramp, nsamples=params['n_samples'])
                end_time_test = time.time()
                if np.any(np.isnan(samples)):
                    print('Epoch: {}, found nans in samples. Not making plots'.format(epoch))
                    for k,s in enumerate(samples):
                        if np.any(np.isnan(s)):
                            print(k,s)
                    KL_est = [-1,-1,-1]
                else:
                    print('Epoch: {}, run {} Testing time elapsed for {} samples: {}'.format(epoch,run,params['n_samples'],end_time_test - start_time_test))
                    KL_est = plot_posterior(samples,x_batch_test[0,:],epoch,step,all_other_samples=bilby_samples[:,step,:],run=plot_dir)
                    _ = plot_posterior(samples,x_batch_test[0,:],epoch,step,run=plot_dir)
                KL_samples.append(KL_est)

            # plot KL evolution
            #plot_KL(np.reshape(np.array(KL_samples),[-1,params['r'],len(params['samplers'])]),plot_cadence,run=plot_dir)

        # load more noisefree training data back in
        if epoch % 10 == 0:
            x_data_train, y_data_train, _, snrs_train = load_data(params,bounds,fixed_vals,params['train_set_dir'],params['inf_pars'],silent=True)

            # augment the data for this chunk - randomize phase and arrival time
            # Randomize phase if inferring phase
#            if np.any([r=='phase' for r in params['inf_pars']]):
            print('... Adding extra phase randomization.')
            old_phase = bounds['phase_min'] + tf.boolean_mask(x_data_train,masks["phase_mask"],axis=1)*(bounds['phase_max'] - bounds['phase_min'])
            new_x = tf.random.uniform(shape=tf.shape(old_phase), minval=0.0, maxval=1.0, dtype=tf.dtypes.float32)
            new_phase = bounds['phase_min'] + new_x*(bounds['phase_max'] - bounds['phase_min'])            
            x_data_train = tf.gather(tf.concat([tf.reshape(tf.boolean_mask(x_data_train,masks["not_phase_mask"],axis=1),[-1,tf.shape(x_data_train)[1]-1]), tf.reshape(new_x,[-1,1])],axis=1),tf.constant(masks["idx_phase_mask"]),axis=1)
            phase_correction = -1.0*tf.complex(tf.cos(new_phase-old_phase),tf.sin(new_phase-old_phase))
            phase_correction = tf.tile(tf.expand_dims(phase_correction,axis=1),(1,len(params["det"]),tf.shape(y_data_train)[1]/2 + 1))

            # Add random time shifts if inferring time
            if np.any([r=='geocent_time' for r in params['inf_pars']]):
                print('... Adding extra time randomization.')
                old_geocent = bounds['geocent_time_min'] + tf.boolean_mask(x_data_train,masks["geocent_mask"],axis=1)*(bounds['geocent_time_max'] - bounds['geocent_time_min'])
                new_x = tf.random.uniform(shape=tf.shape(old_geocent), minval=0.0, maxval=1.0, dtype=tf.dtypes.float32)
                new_geocent = bounds['geocent_time_min'] + new_x*(bounds['geocent_time_max'] - bounds['geocent_time_min'])
                x_data_train = tf.gather(tf.concat([tf.reshape(tf.boolean_mask(x_data_train,masks["not_geocent_mask"],axis=1),[-1,tf.shape(x_data_train)[1]-1]), tf.reshape(new_x,[-1,1])],axis=1),tf.constant(masks["idx_geocent_mask"]),axis=1)
                fvec = tf.range(params['ndata']/2 + 1)/params['duration']
                time_correction = -2.0*np.pi*fvec*(new_geocent-old_geocent)
                time_correction = tf.complex(tf.cos(time_correction),tf.sin(time_correction))
                time_correction = tf.tile(tf.expand_dims(time_correction,axis=1),(1,len(params["det"]),1))

            # randomise distance    
            old_d = bounds['luminosity_distance_min'] + tf.boolean_mask(x_data_train,masks["dist_mask"],axis=1)*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
            new_x = tf.random.uniform(shape=tf.shape(old_d), minval=0.0, maxval=1.0, dtype=tf.dtypes.float32)
            new_d = bounds['luminosity_distance_min'] + new_x*(bounds['luminosity_distance_max'] - bounds['luminosity_distance_min'])
            x_data_train = tf.gather(tf.concat([tf.reshape(tf.boolean_mask(x_data_train,masks["not_dist_mask"],axis=1),[-1,tf.shape(x_data_train)[1]-1]), tf.reshape(new_x,[-1,1])],axis=1),tf.constant(masks["idx_dist_mask"]),axis=1)
            dist_scale = tf.tile(tf.expand_dims(old_d/new_d,axis=1),(1,tf.shape(y_data_train)[1],1))
            

            y_data_train_fft = tf.signal.rfft(tf.transpose(y_data_train,[0,2,1]))*phase_correction*time_correction
            y_data_train = tf.transpose(tf.signal.irfft(y_data_train_fft),[0,2,1])

            # add noise and randomise distance again
            y_normscale = tf.cast(params['y_normscale'], dtype=tf.float32)
            y_data_train = (y_data_train*dist_scale + noiseamp*tf.random.normal(shape=tf.shape(y_data_train), mean=0.0, stddev=1.0, dtype=tf.float32))/y_normscale

            train_dataset = (tf.data.Dataset.from_tensor_slices((x_data_train,y_data_train))
                     .shuffle(train_size).batch(batch_size))


def run_vitc(params, x_data_train, y_data_train, x_data_val, y_data_val, x_data_test, y_data_test, y_data_test_noisefree, save_dir, truth_test, bounds, fixed_vals, bilby_samples, snrs_test=None):

    epochs = params['num_iterations']
    train_size = params['load_chunk_size']
    batch_size = params['batch_size']
    val_size = params['val_dataset_size']
    test_size = params['r']
    plot_dir = params['plot_dir']
    plot_cadence = int(0.5*params['plot_interval'])
    # Include the epoch in the file name (uses `str.format`)
    checkpoint_path = "inverse_model_%s/model.ckpt" % params['run_label']
    checkpoint_dir = os.path.dirname(checkpoint_path)
    make_paper_plots = params['make_paper_plots']
    hyper_par_tune = False

    # if doing hour angle, use hour angle bounds on RA
    bounds['ra_min'] = convert_ra_to_hour_angle(bounds['ra_min'],params,None,single=True)
    bounds['ra_max'] = convert_ra_to_hour_angle(bounds['ra_max'],params,None,single=True)
    print('... converted RA bounds to hour angle')

    # load the training data
    if not make_paper_plots:
        train_dataset = DataLoader(params["train_set_dir"],params = params,bounds = bounds, masks = masks,fixed_vals = fixed_vals, chunk_batch = 40) 
        validation_dataset = DataLoader(params["val_set_dir"],params = params,bounds = bounds, masks = masks,fixed_vals = fixed_vals, chunk_batch = 2)

    x_data_test, y_data_test_noisefree, y_data_test, snrs_test = load_data(params,bounds,fixed_vals,params['test_set_dir'],params['inf_pars'],test_data=True)
    y_data_test = y_data_test[:params['r'],:,:]; x_data_test = x_data_test[:params['r'],:]

    # load precomputed samples
    bilby_samples = []
    for sampler in params['samplers'][1:]:
        bilby_samples.append(load_samples(params,sampler, bounds = bounds))
    bilby_samples = np.array(bilby_samples)
    #bilby_samples = np.array([load_samples(params,'dynesty'),load_samples(params,'ptemcee'),load_samples(params,'cpnest')])

    test_dataset = (tf.data.Dataset.from_tensor_slices((x_data_test,y_data_test))
                    .batch(1))

    train_loss_metric = tf.keras.metrics.Mean('train_loss', dtype=tf.float32)
    train_summary_writer = tf.summary.create_file_writer(train_log_dir)

    if params['resume_training']:
        model = CVAE(x_data_train.shape[1], params['ndata'],
                     y_data_train.shape[2], params['z_dimension'], params['n_modes'], params, bounds = bounds, masks = masks)
        # Load the previously saved weights
        latest = tf.train.latest_checkpoint(checkpoint_dir)
        model.load_weights(latest)
        print('... loading in previous model %s' % checkpoint_path)
    else:
        model = CVAE(x_data_test.shape[1], params['ndata'],
                     y_data_test.shape[2], params['z_dimension'], params['n_modes'], params, bounds, masks)


    # Make publication plots
    if make_paper_plots:
        print('... Making plots for publication.')
        # Load the previously saved weights
        latest = tf.train.latest_checkpoint(checkpoint_dir)
        model.load_weights(latest)
        print('... loading in previous model %s' % checkpoint_path)
        paper_plots(test_dataset, y_data_test, x_data_test, model, params, plot_dir, run, bilby_samples)
        return

    # start the training loop
    train_loss = np.zeros((epochs,3))
    val_loss = np.zeros((epochs,3))
    ramp_start = params['ramp_start']
    ramp_length = params['ramp_end']
    ramp_cycles = 1
    KL_samples = []


    optimizer = tf.keras.optimizers.Adam(1e-5)

    # Keras hyperparameter optimization
    if hyper_par_tune:
        import keras_hyper_optim
        del model
        keras_hyper_optim.main(train_dataset, val_dataset)
        exit()

    # log params used for this run
    path = params['plot_dir']
    shutil.copy('./vitamin_c_new.py',path)
    shutil.copy('./params_files/params.json',path)

    print("Loading intitial data....")
    train_dataset.load_next_chunk()
    validation_dataset.load_next_chunk()
    
    model.compile()

    for epoch in range(1, epochs + 1):

        train_loss_kl_q = 0.0
        train_loss_kl_r1 = 0.0
        start_time_train = time.time()
        if params['resume_training']:
            ramp = ramp = tf.convert_to_tensor(1.0)
            print('... Not using ramp.')
        else:
            ramp = tf.convert_to_tensor(ramp_func(epoch,ramp_start,ramp_length,ramp_cycles), dtype=tf.float32)

        for step in range(len(train_dataset)):
            y_batch_train, x_batch_train = train_dataset[step]
            if len(y_batch_train) == 0:
                print("NO data: ", train_dataset.chunk_iter, np.shape(y_batch_train))
            #print(step, np.shape(y_batch_train),np.shape(x_batch_train))
            temp_train_r_loss, temp_train_kl_loss = model.train_step(x_batch_train, y_batch_train, optimizer, ramp=ramp)
            train_loss[epoch-1,0] += temp_train_r_loss
            train_loss[epoch-1,1] += temp_train_kl_loss
        train_loss[epoch-1,2] = train_loss[epoch-1,0] + ramp*train_loss[epoch-1,1]
        train_loss[epoch-1,:] /= float(step+1)
        end_time_train = time.time()
        with train_summary_writer.as_default():
            tf.summary.scalar('loss', train_loss_metric.result(), step=epoch)
        train_loss_metric.reset_states()

        start_time_val = time.time()
        for step in range(len(validation_dataset)):
            y_batch_val, x_batch_val = validation_dataset[step]
            temp_val_r_loss, temp_val_kl_loss = model.compute_loss(x_batch_val, y_batch_val)
            val_loss[epoch-1,0] += temp_val_r_loss
            val_loss[epoch-1,1] += temp_val_kl_loss
        val_loss[epoch-1,2] = val_loss[epoch-1,0] + ramp*val_loss[epoch-1,1]
        val_loss[epoch-1,:] /= float(step+1)
        end_time_val = time.time()

        print('Epoch: {}, Run {}, Training RECON: {}, KL: {}, TOTAL: {}, time elapsed: {}'
            .format(epoch, run, train_loss[epoch-1,0], train_loss[epoch-1,1], train_loss[epoch-1,2], end_time_train - start_time_train))
        print('Epoch: {}, Run {}, Validation RECON: {}, KL: {}, TOTAL: {}, time elapsed {}'
            .format(epoch, run, val_loss[epoch-1,0], val_loss[epoch-1,1], val_loss[epoch-1,2], end_time_val - start_time_val))

        if epoch % params['save_interval'] == 0:
            # Save the weights using the `checkpoint_path` format
            model.save_weights(checkpoint_path)
            print('... Saved model %s ' % checkpoint_path)

        # update loss plot
        plot_losses(train_loss, val_loss, epoch, run=plot_dir)
        if epoch > ramp_start + ramp_length + 2:
            plot_losses_zoom(train_loss, val_loss, epoch, run=plot_dir, ind_start = ramp_start + ramp_length)

        # generate and plot posterior samples for the latent space and the parameter space 
        if epoch % plot_cadence == 0:
            for step, (x_batch_test, y_batch_test) in test_dataset.enumerate():             
                mu_r1, z_r1, mu_q, z_q = model.gen_z_samples(x_batch_test, y_batch_test, nsamples=1000)
                plot_latent(mu_r1,z_r1,mu_q,z_q,epoch,step,run=plot_dir)
                start_time_test = time.time()
                samples = model.gen_samples(y_batch_test, ramp=ramp, nsamples=params['n_samples'])
                end_time_test = time.time()
                if np.any(np.isnan(samples)):
                    print('Epoch: {}, found nans in samples. Not making plots'.format(epoch))
                    for k,s in enumerate(samples):
                        if np.any(np.isnan(s)):
                            print(k,s)
                    KL_est = [-1,-1,-1]
                else:
                    print('Epoch: {}, run {} Testing time elapsed for {} samples: {}'.format(epoch,run,params['n_samples'],end_time_test - start_time_test))
                    KL_est = plot_posterior(samples,x_batch_test[0,:],epoch,step,all_other_samples=bilby_samples[:,step,:],run=plot_dir)
                    _ = plot_posterior(samples,x_batch_test[0,:],epoch,step,run=plot_dir)
                KL_samples.append(KL_est)

            # plot KL evolution
            #plot_KL(np.reshape(np.array(KL_samples),[-1,params['r'],len(params['samplers'])]),plot_cadence,run=plot_dir)

        # iterate the chunk, i.e. load more noisefree data in
        if epoch % 10 == 0:
            print("Loading the next Chunk ...")
            train_dataset.load_next_chunk()






















